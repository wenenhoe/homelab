# step-ca: Internal PKI

`step-ca` is a private X.509 certificate authority for internal,
service-to-service TLS — signing certs for the lab's own `.{{ lab_domain
}}`-style names, not proving control to a public CA. `lldap_cert` and
`tinyauth_ca_trust` (see [`lldap.md`](lldap.md)) are its first two real
consumers: lldap's LDAPS cert comes from here, and tinyauth trusts it.

## Custom entrypoint, not `DOCKER_STEPCA_INIT_*`

`scripts/entrypoint.sh` runs `step ca init` by hand instead of using
the official image's `DOCKER_STEPCA_INIT_*` auto-init, followed by one
`step ca provisioner update --x509-default-dur` call to set the claim
duration explicitly. Both only run once, gated on the same
`config/ca.json`-doesn't-exist check the stock entrypoint uses — a
restart with an already-initialized `data` volume skips straight to
`exec step-ca`. See
[ADR 0004](decisions/0004-stepca-custom-entrypoint-not-docker-init-vars.md)
for why: the stock auto-init can't keep the CA's own password and the
provisioner's password independent, and has no flag for claim
durations.

The claim duration itself is set to 720h, not step-ca's own 24h
default — see
[ADR 0005](decisions/0005-stepca-cert-duration-720h.md), which flags
that decision's original premise as stale now that `lldap_cert`'s
renewal timer exists.

## DNS names and the health check

`STEP_CA_DNS_NAMES` (`configs/env.j2`) lists `step-ca` before
`step-ca.{{ caddy_domain }}`, and the order of the *first* name matters:
`step ca init` writes it into `defaults.json`'s `ca-url`, and the
upstream image's own `HEALTHCHECK` runs `step ca health` against
exactly that URL, from inside the container. `step-ca` — this compose
service's own name, which Docker's embedded DNS resolves back to the
container itself on `caddy-proxy` — has to stay first, or the health
check tries to reach a name the container can't resolve to itself and
reports unhealthy even though the CA is running fine. This is a
well-documented footgun upstream; several people have hit exactly this
running step-ca behind a reverse proxy or on Docker Swarm.

## Network

Reachable only on `caddy-proxy`, by container name (`step-ca:9000`) —
no Caddy vhost (no `caddy:` key in its `app_registry` entry, the same
pattern `bind9` uses), and no host port published. A CA's admin/signing
API isn't something to put behind a reverse proxy the way an ordinary
web app is.

No host-level access needed: every consumer of this CA, including
`lldap_cert`'s own systemd renewal unit and one-time issuance task (see
[`lldap.md`](lldap.md)), runs `step` via the official `smallstep/step-cli`
image rather than a host-installed binary — a container on `caddy-proxy`
that reaches this one by its real container name, the same way any
other consumer would. Nothing in this repo ever needed a host process
to resolve "step-ca" by name, so there's no loopback port publish or
extra SAN to carry for that purpose.

## Requesting a certificate: manual test client

From any container joined to `caddy-proxy` with the `step` CLI
available:

```sh
docker run --rm -it --network caddy-proxy smallstep/step-cli sh
```

Inside that shell:

```sh
# Trust this CA's root — prompts for the fingerprint shown when step-ca
# first initialized (`docker compose logs step-ca` on the host, or
# `docker exec step-ca step certificate fingerprint /home/step/certs/root_ca.crt`).
step ca bootstrap --ca-url https://step-ca:9000 --fingerprint <fingerprint>

# Issue a cert — prompts for STEP_CA_PROVISIONER_PASSWORD
# (ansible/files/secrets/step-ca-provisioner-password on the controller).
step ca certificate test-client.{{ lab_domain }} test.crt test.key \
  --provisioner internal-services
```

`lldap_cert`'s own initial-issuance task
(`ansible/roles/lldap_cert/tasks/main.yaml`) is the real, live version
of this — a single `step ca certificate` call with `--san`/`--password-file`/
`--ca-url`/`--root` set explicitly, not the interactive
`step ca bootstrap` flow above. That's the reference for a future
consumer to follow — this repo's "one explanation, one home" convention
expects that consumer's own docs to point back here, rather than
re-explaining provisioner auth or claim duration locally.

## Secrets

`step-ca-password` and `step-ca-provisioner-password`
(`secrets_registry.yaml`, both `hex`/32) are Ansible-generated and
cached like any other secret — see [`secrets.md`](secrets.md). Neither
is externally issued, so neither needs `format: manual`.
