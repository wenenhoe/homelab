# 0022. One broad AppRole for `controller`, not split per secret family or by consumer

**Status:** Accepted

## Context

This design originally assumed one
automated consumer — "AppRole for the Ansible controller, one policy
per secret-path family." A separate, not-yet-built proposal exists for
a dedicated automation host (`cd_agent`) that would become the sole
path to prod deploys and take over the rotation/freshness jobs
[0018](0018-openbao-repoint-not-native-plugin.md) schedules — but that
host doesn't exist yet, and `controller` (the operator's own machine)
is the only automation identity that exists today. Designing one
static AppRole layout as if that future identity already existed would
either over-scope `controller` permanently or under-scope it for what
it actually has to do right now.

One more consumer surfaced once this was actually
built: `openbao-backup-restore.md`'s snapshot-push script currently
needs a human to export the root token by hand
([0023](0023-openbao-snapshot-push-standalone.md)'s "Why manual"
section explains what eventually fixes that), but that script runs on
`security` itself, not from `controller`. Since this design has exactly one
automation identity, giving the snapshot job its own AppRole would
mean a third identity solely for one read-only path — the Decision
below folds it into `controller`'s policy instead. This does mean
`controller`'s `secret_id` ends up cached on two hosts (the operator's
laptop and `security`) rather than one; see
[`openbao-auth.md`](../openbao-auth.md) for the runbook.

`cd_agent` has a fixed LAN IP; `controller` doesn't (laptop, DHCP) —
confirmed directly rather than assumed. That asymmetry is the other
input here: OpenBao's AppRole auth method supports binding both the
login step and the resulting token to specific CIDR blocks
(`secret_id_bound_cidrs`, `token_bound_cidrs`, per OpenBao's own
AppRole API reference), which is only usable for an identity with a
stable address.

## Decision

One AppRole, `controller`, with one policy covering everything except
recovery-critical material (which never enters Vault at all, per
[0017](0017-openbao-bootstrap-secret-split.md)): read/write on
`secret/data/hosts/*` (mirroring the `security`/`services`/`storage`/
`play` `host_vars` split) and on both
`secret/data/cloud_credentials/leaf/*` and
`secret/data/cloud_credentials/rotation/*`, plus read-only on
`sys/storage/raft/snapshot` for the reason above. The first three
match today's reality — one human/machine already does everything via
the file cache — so it's not a new exposure, just the same scope moved
to Vault; the snapshot path is new scope, but read-only and narrow
enough (one path, no `sudo` capability required — confirmed against a
real snapshot-agent policy example, not just the endpoint's own docs)
that it doesn't change the "one broad-but-bounded identity" shape this
era is built around. No `secret_id_bound_cidrs`/`token_bound_cidrs` on
this role:
`controller` has no stable address to bind to, and this era is
transitional by design.

## Consequences

- `controller`'s AppRole is intentionally broad and intentionally
  temporary — it's built around being the only automation identity
  that exists today, not as a permanent shape. If a dedicated
  automation host is ever built to take over prod deploys and
  rotation, this AppRole's removal is a required step of that work,
  not an optional cleanup. `disaster-recovery.md`/`ansible.md` should
  say so once that lands, so a future reader doesn't assume it's
  permanent.
