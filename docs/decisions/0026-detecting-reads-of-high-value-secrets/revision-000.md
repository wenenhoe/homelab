---
id: ADR-0026
revision: 0
type: adr
title: Detecting reads of high-value secrets
short: High-value secret read alerts
solution: A declarative stdout audit device plus a least-privilege watcher
summary: Every read of the R2 admin token's path is visible and raises an alert.
topic: secrets-store
status: superseded
superseded_by: 1
related: [ADR-0020, ADR-0110]
---

# 0026. Detecting reads of high-value secrets

## Decision

Enable a permanent `audit "file"` device via declarative server
config (`docker/openbao/configs/openbao.hcl.j2`), writing to `stdout`,
captured by Docker's own log driver — not the API/CLI route, not a
new volume.

Add an explicit `logging:` block to the `openbao` compose service
(`driver: json-file`, `options: {max-size: "50m", max-file: "5"}` as
a starting point, adjustable) before this lands — mandatory, not a
follow-up, given the audit device is what turns the existing
uncapped-log gap into a real risk.

Build a dedicated watcher: a persistent systemd service on `security`
parsing `docker logs -f openbao`'s stdout, matching only
`type: "response"` lines whose `request.path` equals the R2 rotation
token's Vault path
(`secret/data/cloud_credentials/rotation/_rotation-key-cloudflare-r2-token`),
alerting via the same `hosts/all/telegram/*` Vault-backed path
`check_freshness.py` (renamed: `check_credential_expiry.py`) already uses. Every other line is parsed only
far enough to check the path, then discarded — never persisted or
forwarded.

The watcher authenticates with its own new AppRole, read-only on
`secret/data/hosts/all/telegram/*` alone — not controller's existing
broad AppRole. Its job and risk profile (a persistent process
with no need for anything controller can reach) don't match
controller's, and reusing it would grow controller's blast radius for
no reason.

The watcher pushes a periodic heartbeat via the same mechanism
`ansible/roles/uptime_kuma_push` already uses elsewhere in this repo,
so a crashed or disconnected watcher is visibly flagged instead of
silently going dark.
