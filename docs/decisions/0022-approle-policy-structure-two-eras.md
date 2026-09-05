# 0022. AppRole/policy structure: controller today, split cd_agent roles after the CD-runner stage

**Status:** Proposed

## Context

The migration roadmap's auth/policy stage originally assumed one
automated consumer — "AppRole for the Ansible controller, one policy
per secret-path family."
[0020](0020-pull-based-cd-agent-not-self-hosted-github-runner.md)
changed that: `cd_agent` becomes the sole path to prod deploys once it
exists, and also runs the rotation/freshness jobs
[0018](0018-openbao-repoint-not-native-plugin.md) schedules. But
`cd_agent` isn't built until the CD-runner stage — the roadmap's last
stage — while everything from auth setup through the file-cache
cutover still runs entirely from `controller`, the only automation
identity that exists at that point. Designing one static AppRole
layout for the whole roadmap would either over-scope `controller`
permanently or under-scope it during the stages that need it to do
everything.

`cd_agent` has a fixed LAN IP; `controller` doesn't (laptop, DHCP) —
confirmed directly rather than assumed. That asymmetry is the other
input here: OpenBao's AppRole auth method supports binding both the
login step and the resulting token to specific CIDR blocks
(`secret_id_bound_cidrs`, `token_bound_cidrs`, per OpenBao's own
AppRole API reference), which is only usable for an identity with a
stable address.

## Decision

Two eras, not one static design:

**Era A (auth setup through the file-cache cutover, `controller`
only).** One AppRole,
`controller`, with one policy covering everything except
recovery-critical material (which never enters Vault at all, per
[0017](0017-openbao-bootstrap-secret-split.md)): read/write on
`secret/data/hosts/*` (mirroring the `security`/`services`/`storage`/
`play` `host_vars` split) and on both
`secret/data/cloud_credentials/leaf/*` and
`secret/data/cloud_credentials/rotation/*`. This matches today's
reality — one human/machine already does everything via the file
cache — so it's not a new exposure, just the same scope moved to
Vault. No `secret_id_bound_cidrs`/`token_bound_cidrs` on this role:
`controller` has no stable address to bind to, and this era is
transitional by design.

**Era B (once the CD-runner stage lands and `cd_agent` exists).** Two
AppRoles, both bound to
`cd_agent`'s fixed LAN IP via `secret_id_bound_cidrs` and
`token_bound_cidrs`:

- `cd-agent-deploy` — read-only on `secret/data/hosts/*` and
  `secret/data/cloud_credentials/leaf/*`. No access to
  `cloud_credentials/rotation/*` at all — a compromised deploy job
  can't reach any master-tier credential.
- `cd-agent-rotation` — create/update (and read) on
  `secret/data/cloud_credentials/leaf/*` and
  `secret/data/cloud_credentials/rotation/*`. No access to
  `secret/data/hosts/*` — the rotation job has no business touching
  app secrets.

Both AppRoles live on the same physical host, so the CIDR bind
separates `cd_agent` from everything else on the network — it does
**not** separate the two jobs from each other. That separation is
policy-only, which is why it matters that `cd-agent-deploy` and
`cd-agent-rotation` are two distinct AppRoles rather than one shared
identity with a union of both policies.

Each `cd_agent` job authenticates fresh per invocation — a short-lived
token per run (matching the deploy job's every-2-minute cadence per
[0020](0020-pull-based-cd-agent-not-self-hosted-github-runner.md)),
not one long-lived token held in memory between runs. The `secret_id`
itself is the credential that persists on `cd_agent`'s disk
indefinitely (`secret_id_num_uses: 0`, no expiry) — a single-use
`secret_id` would mean re-issuing it every run, which defeats the
point of it being a durable bootstrap secret for an always-on box. It
carries the same on-disk exposure as any other cached credential in
this repo; the CIDR bind and narrow policy are what limit its blast
radius, not its use-count. It's generated once during `cd_agent`'s
own provisioning (the human-attended, decoupled play
[0020](0020-pull-based-cd-agent-not-self-hosted-github-runner.md)
already defines), ideally via Vault's response-wrapping so the raw
value never sits in a terminal scrollback.

Once `cd-agent-deploy`/`cd-agent-rotation` are live and proven,
`controller`'s AppRole is deleted outright, not narrowed. From that
point, `controller` holds no standing Vault credential at all — any
rare admin/debug/break-glass access uses a token generated on demand
by whoever already holds Vault access (e.g. during a restore drill),
narrowly scoped and short-lived, never persisted to disk.

## Consequences

- `controller`'s Era A AppRole is intentionally broad and
  intentionally temporary — its removal is a required step of the
  CD-runner stage,
  not an optional cleanup. `disaster-recovery.md`/`ansible.md` should
  say so once this lands, so a future reader doesn't assume it's
  permanent.
- Token lifetime (`token_ttl`) per `cd_agent` invocation is a build
  parameter for the auth/policy stage, not decided here: long enough
  for one deploy/rotation run to complete, short enough that a leaked
  token from one run doesn't outlive it by much.
- `secret_id` rotation cadence for `cd_agent`'s two AppRoles isn't
  decided here either — periodically re-running `cd_agent`'s own
  provisioning is the natural mechanism, matching this repo's existing
  human-attended pattern for cloud rotation-key bootstrap, but no
  schedule is set.
- If `cd_agent`'s LAN IP ever changes, both AppRoles' CIDR binds need
  updating — a manual step, not something the agent's own jobs could
  safely do (it would be the job editing its own trust boundary).
