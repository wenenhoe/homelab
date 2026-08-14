# step-ca: Internal PKI

`step-ca` is a private X.509 certificate authority for internal,
service-to-service TLS — signing certs for the lab's own `.{{ lab_domain
}}`-style names, not proving control to a public CA. It's standalone
infrastructure in this PR: nothing consumes it yet. lldap moving onto it
is a separate, already-scoped follow-up.

## Why a custom entrypoint instead of `DOCKER_STEPCA_INIT_*`

The official image ships its own non-interactive bootstrap, driven by
`DOCKER_STEPCA_INIT_*` env vars, and only initializes if
`config/ca.json` doesn't exist yet — that idempotency (and persisting
the CA's identity in an external volume rather than an image build
layer) is why this uses the official image at all, rather than baking
`step ca init` into a Dockerfile at build time the way the reference
step-ca setup this was adapted from does. A build-time `step ca init`
regenerates a fresh random root key on every image rebuild, silently
rotating trust for every consumer that's already bootstrapped against
the old one.

That said, the stock auto-init (`docker/entrypoint.sh` in
`smallstep/certificates`) can't fully express this repo's design:

- It encrypts the CA's own keys and the initial JWK provisioner's key
  with the **same** password — `DOCKER_STEPCA_INIT_PASSWORD`/
  `_FILE` gets copied to both `secrets/password` and
  `secrets/provisioner_password`. There's no separate provisioner
  password.
- It has no flag for a provisioner's claim durations
  (`defaultTLSCertDuration`) — only `step ca provisioner update`
  (a separate, later command) can set that.

`scripts/entrypoint.sh` runs the same underlying command
(`step ca init`) by hand instead, so `step-ca-password` and
`step-ca-provisioner-password` (`secrets_registry.yaml`) stay genuinely
independent, followed by one `step ca provisioner update
--x509-default-dur` call to set the claim explicitly. Both only run
once, gated on the same `config/ca.json`-doesn't-exist check the stock
entrypoint uses — a restart with an already-initialized `data` volume
skips straight to `exec step-ca`. Smallstep's own production-considerations
guide recommends exactly this — securing the default provisioner with a
different password than the CA's signing keys by passing separate
`--password-file`/`--provisioner-password-file` — so this isn't just
working around a gap, it's the documented-recommended setup the stock
auto-init doesn't happen to offer a shortcut for.

## Why the cert duration is 720h, not step-ca's own 24h default

step-ca's own default (24h) assumes a consumer is always renewing
constantly in the background — appropriate once something like
`step ca renew --daemon` exists in this repo, the way the reference
setup's `stepca-provision.sh`/`stepca-renew.sh` do it. Nothing here
runs that yet, so a 24h cert would just expire unattended. 720h (30
days) is a deliberate placeholder for "renewed by hand until a
follow-up PR adds renewal automation," not a value to leave in place
long-term — revisit it downward (back toward step-ca's own 24h
philosophy) once that automation lands.

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

A future real consumer follows the same two commands as part of its own
startup — this is the reference this repo's "one explanation, one home"
convention expects that consumer's own docs to point back to, rather
than re-explaining provisioner auth or claim duration locally.

## Secrets

`step-ca-password` and `step-ca-provisioner-password`
(`secrets_registry.yaml`, both `hex`/32) are Ansible-generated and
cached like any other secret — see [`secrets.md`](secrets.md). Neither
is externally issued, so neither needs `format: manual`.
