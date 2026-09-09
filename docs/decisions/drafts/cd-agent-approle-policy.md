# Two CIDR-bound AppRoles for the CD agent, replacing controller's broad grant

**Status:** Draft

## Context

[0022](../0022-approle-policy-structure-two-eras.md) gives `controller`
one broad AppRole because it's the only automation identity that
exists today. A separate, not-yet-built proposal (see
[`pull-based-cd-agent-not-self-hosted-github-runner.md`](pull-based-cd-agent-not-self-hosted-github-runner.md))
would add a dedicated automation host (`cd_agent`) that becomes the
sole path to prod deploys and takes over the rotation/freshness jobs
[0018](../0018-openbao-repoint-not-native-plugin.md) schedules. Once
that host exists, one broad identity stops being the right shape:
`cd_agent` would run two categories of unattended, prod-touching work
(deploy/maintenance, and credential rotation/freshness) that don't
need the same access to each other's material.

`cd_agent`, as proposed, would have a fixed LAN IP — unlike
`controller` (the operator's laptop, DHCP), which is why 0022's grant
has no CIDR binding. OpenBao's AppRole auth method supports binding
both the login step and the resulting token to specific CIDR blocks
(`secret_id_bound_cidrs`, `token_bound_cidrs`, per OpenBao's own
AppRole API reference) — usable only for an identity with a stable
address.

## Decision

Two AppRoles, both bound to `cd_agent`'s fixed LAN IP via
`secret_id_bound_cidrs` and `token_bound_cidrs`:

- `cd-agent-deploy` — read-only on `secret/data/hosts/*` and
  `secret/data/cloud_credentials/leaf/*`. No access to
  `cloud_credentials/rotation/*` at all — a compromised deploy job
  can't reach any master-tier credential.
- `cd-agent-rotation` — create/update (and read) on
  `secret/data/cloud_credentials/leaf/*` and
  `secret/data/cloud_credentials/rotation/*`. No access to
  `secret/data/hosts/*` — the rotation job has no business touching
  app secrets.

Both AppRoles would live on the same physical host, so the CIDR bind
separates `cd_agent` from everything else on the network — it does
**not** separate the two jobs from each other. That separation is
policy-only, which is why `cd-agent-deploy` and `cd-agent-rotation`
need to be two distinct AppRoles rather than one shared identity with
a union of both policies.

Each `cd_agent` job would authenticate fresh per invocation — a
short-lived token per run, not one long-lived token held in memory
between runs. The `secret_id` itself is the credential that persists
on `cd_agent`'s disk indefinitely (`secret_id_num_uses: 0`, no
expiry) — a single-use `secret_id` would mean re-issuing it every run,
which defeats the point of it being a durable bootstrap secret for an
always-on box. It carries the same on-disk exposure as any other
cached credential in this repo; the CIDR bind and narrow policy are
what would limit its blast radius, not its use-count. It would be
generated once during `cd_agent`'s own provisioning, ideally via
Vault's response-wrapping so the raw value never sits in a terminal
scrollback.

Once `cd-agent-deploy`/`cd-agent-rotation` are live and proven,
`controller`'s AppRole is deleted outright, not narrowed. From that
point, `controller` would hold no standing Vault credential at all —
any rare admin/debug/break-glass access uses a token generated on
demand by whoever already holds Vault access (e.g. during a restore
drill), narrowly scoped and short-lived, never persisted to disk.

## Assumptions

- **Claim:** `cd_agent` exists as a dedicated, always-on LAN host with
  a fixed IP address.
  **Breaks if wrong:** the CIDR-bound design above requires a stable
  address to bind to; without one, `secret_id_bound_cidrs`/
  `token_bound_cidrs` can't be set the way this draft assumes, and the
  whole "CIDR bind separates `cd_agent` from the network" argument
  doesn't hold.
  **Checked by:** confirmed directly once `cd_agent`'s host is
  actually provisioned — a provisioning fact, not something needing a
  spike.
- **Claim:** the deploy job and rotation job's risk profiles are
  different enough to justify two separate AppRoles rather than one
  shared identity.
  **Breaks if wrong:** if the two jobs' actual credential needs turn
  out to overlap heavily, or the operational overhead of two AppRoles
  outweighs the isolation benefit, the two-role split collapses to one
  shared identity, changing the whole grant structure above.
  **Checked by:** revisit once `cd_agent`'s actual job scripts exist
  and their real credential needs are known.

## Consequences

- Token lifetime (`token_ttl`) per `cd_agent` invocation isn't decided
  here: long enough for one deploy/rotation run to complete, short
  enough that a leaked token from one run doesn't outlive it by much.
- `secret_id` rotation cadence for `cd_agent`'s two AppRoles isn't
  decided here either — periodically re-running `cd_agent`'s own
  provisioning is the natural mechanism, matching this repo's existing
  human-attended pattern for cloud rotation-key bootstrap, but no
  schedule is set.
- If `cd_agent`'s LAN IP ever changes, both AppRoles' CIDR binds need
  updating — a manual step, not something the agent's own jobs could
  safely do (it would be the job editing its own trust boundary).
