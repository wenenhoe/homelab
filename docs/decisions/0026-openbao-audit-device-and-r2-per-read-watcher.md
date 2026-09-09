# 0026. Permanent stdout audit device, plus a dedicated watcher, for the R2 admin-token per-read alert

**Status:** Accepted

## Context

[0019](0019-r2-admin-token-into-openbao.md) requires an alert on every
read of the R2 admin token's Vault path, calling the audit log "the
natural source" but leaving the exact mechanism to this stage.
OpenBao currently has no audit device configured at all
([`openbao.md`](../openbao.md)).

Two ways to enable one. API-driven (`bao audit enable`) requires
`unsafe_allow_api_audit_creation = true` in server config on OpenBao
2.3.2+ — a flag added specifically to close a real RCE in the audit
subsystem (CVE-2025-54997). Reopening it to get this feature would
reopen what that fix closed, and is rejected on that basis alone; it's
moot anyway, since this repo currently has no working path to a
root/`sudo`-capable token to call it with. **Declarative audit config**
— a server HCL stanza,
available since OpenBao 2.4.0, applied at restart/SIGHUP, no token or
API call needed — is the supported alternative and has no such
exposure.

Confirmed live against the real instance (2.6.2): `request.path` is
literal, not hashed. A single `type: "response"` line embeds the
entire original request alongside the response, so no request/response
pairing by ID is needed to decide whether to alert. Secret values and
tokens stay HMAC'd even in the response — `probe` came back as
`hmac-sha256:...`, not plaintext.

OpenBao's audit device can't be scoped at the source: every enabled
device receives every request/response system-wide except a small,
fixed, non-configurable exemption list (`sys/init`, `sys/health`,
etc. — [`openbao.md`](../openbao.md)'s own audit docs). Vault's
field-level `exclude` capability is a HashiCorp Enterprise-only
feature with no OpenBao equivalent, and even there it only redacts
fields within an entry that's still written, not the entry itself.
Any narrowing has to happen downstream, in whatever reads the log.

**Threat model.** Adversary: anyone who already holds root or
`docker`-group access on `security`, or — more consequentially —
anything that later ships this log off that host. Asset: the audit
stream itself — every path, policy name, entity ID, operation, and
timestamp, in plaintext, for every Vault operation; secret values and
tokens stay HMAC'd. Attack path: that adversary gains a full map of
every credential's existence, naming, and access pattern — real
reconnaissance value — without gaining the credential values
themselves. The same adversary already has substantially worse access
at that trust tier (OpenBao's own TLS key, live decrypted traffic), so
the marginal exposure is real but bounded as long as the log stays on
`security` — confirmed no compose service in this repo ships logs
anywhere today (no `logging:` stanza exists on any of them). That
containment is the load-bearing assumption; it needs revisiting the
day any log-shipping/aggregation is added.

Separately: Docker's default `json-file` log driver has no size cap,
and nothing in this repo sets one. Every other service's log volume
scales with app-level events; this is the first whose volume scales
with Vault traffic, including `check_freshness.py`'s own routine
polling — the gap becomes a real disk-growth risk here specifically,
not just a latent one.

A live-tail watcher (`docker logs -f`) is also a new shape of
component for this package: everything else in `cloud_credentials` is
invoke-once. A live-tail can die, or lose its attachment across an
OpenBao container restart, with no signal that it happened —
`check_freshness.py`'s timer-based model doesn't share that failure
mode.

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
`check_freshness.py` already uses. Every other line is parsed only
far enough to check the path, then discarded — never persisted or
forwarded.

The watcher authenticates with its own new AppRole, read-only on
`secret/data/hosts/all/telegram/*` alone — not controller's existing
broad Era A AppRole. Its job and risk profile (a persistent process
with no need for anything controller can reach) don't match
controller's, and reusing it would grow controller's blast radius for
no reason.

The watcher pushes a periodic heartbeat via the same mechanism
`ansible/roles/uptime_kuma_push` already uses elsewhere in this repo,
so a crashed or disconnected watcher is visibly flagged instead of
silently going dark.

## Consequences

- Every Vault operation is now audited in plaintext (paths, policies,
  entities, timing); values and tokens stay HMAC'd. Accepted given no
  log-shipping destination exists today — revisit the day one is
  added.
- [`openbao.md`](../openbao.md)'s "no audit device configured" line
  goes stale the moment this lands; update it alongside this work.
- Another Vault identity now exists alongside `controller`'s broad
  AppRole ([0022](0022-approle-policy-structure-two-eras.md)) — a
  deliberate, narrow exception to that ADR's "one broad identity"
  framing, justified by this component's different job and risk
  profile, not a reconsideration of that design itself.
- This is the first persistent, non-invoke-once process in
  `cloud_credentials`. If a scheduled poll of the log file ever proves
  simpler than a live-tail, that's a legitimate future revisit — the
  live-tail choice here follows from
  [0019](0019-r2-admin-token-into-openbao.md) explicitly wanting
  event-driven alerting, not from polling being ruled out on the
  merits.
- No mechanism exists to reduce what OpenBao itself logs; accepted as
  inherent to enabling any audit device, not specific to this design.
