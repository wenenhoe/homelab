# 0003. Issue lldap's LDAPS cert from the internal step-ca, not certbot + DNS-01

**Status:** Accepted

## Context

lldap's original design (`docker/lldap/compose.yaml`, removed in
`refactor: Remove certbot from lldap`) used a `certbot` container
running `certbot/dns-digitalocean` to issue and renew the LDAPS cert
via DNS-01 against DigitalOcean, plus a second `dockerproxy`
(`tecnativa/docker-socket-proxy`) container whose only job was giving
certbot's deploy-hook a locked-down path to restart `lldap` after a
renewal, without mounting the real Docker socket into `certbot`
itself.

Renewal was an unsupervised shell loop
(`while :; do certbot renew --non-interactive --quiet; sleep 12h & wait; done`)
with no health check and no way to distinguish "renewed fine" from
"silently failed" — the compose file itself carried `# TODO: Add
healthcheck`, `# NOTE: Just loops the renewal script, no daemon/port to
probe`, and `# NOTE: Need more investigation` against that service. The
deploy-hook's restart path had its own silent-failure mode too: if
`/var/run/docker.sock` wasn't reachable through the proxy, it printed a
warning and left the running `lldap` container on the old cert instead
of failing loudly.

## Decision

Replace both containers with two host-level Ansible roles —
`step_ca_client` and `lldap_cert` — that issue and renew the LDAPS cert
from this repo's own internal `step-ca` (see
[`step-ca.md`](../step-ca.md)) instead of an external ACME provider.
Renewal runs as a systemd `cert-renewer@lldap.timer`, adapted from
Smallstep's own canonical renewal-unit pattern, not another
long-running loop in a container.

## Consequences

The `dockerproxy` workaround disappears entirely — nothing needs
Docker-socket access for this anymore, locked-down or otherwise, since
the systemd unit runs as `root` on the host and restarts the container
via `docker compose` directly. A renewal failure is now a failed
systemd unit (`systemctl status cert-renewer@lldap.service`) that pages
a Telegram topic via `OnFailure=`, not a swallowed exception inside a
best-effort shell loop — see
[`lldap.md`](../lldap.md#why-renewal-is-a-systemd-timer-not-an-in-container-daemon)
for the full mechanism.

lldap's LDAPS cert no longer depends on DigitalOcean DNS-01 at all.
Caddy's public wildcard certs are unaffected — those still use
DNS-01 against DigitalOcean, since they need a certificate the public
internet will actually trust, which the internal `step-ca` can't
provide.
