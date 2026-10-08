---
id: ADR-0020
revision: 1
type: adr
title: Automation identity and access scope
short: Automation identity scope
solution: Four CIDR-bound AppRoles for the CD agent (deploy, rotation, freshness and snapshot), retiring controller's broad grant
summary: Which identities may read and write which secret paths, once unattended prod-touching work has more than one category.
topic: secrets-store
status: approved
supersedes: 0
related: [ADR-0017, ADR-0023, ADR-0025, ADR-0044, ADR-0047]
---

# Four CIDR-bound AppRoles for the CD agent, replacing controller's broad grant

## Context

[0020](revision-000.md) gives `controller`
one broad AppRole because it's the only automation identity that
exists today. [ADR 0044 (CD agent trigger)](../0044-prod-automation-trigger-and-execution/revision-000-c.md)
adds a dedicated automation host (`cd_agent`) that becomes the sole
path to prod deploys and takes over the rotation/freshness jobs
[0023](../0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md) schedules.
`cd_agent` runs four categories of unattended, prod-touching work
(deploy/maintenance, credential rotation, the freshness check, and the
OpenBao snapshot push) that don't need the same access to each other's
material, so one broad identity stops being the right shape. ADR 0044 gives each job its own timer and
its own Unix user, and requires the host to have a fixed address, unlike
the controller's AppRole today, which has no CIDR binding.

OpenBao's AppRole auth method supports binding
both the login step and the resulting token to specific CIDR blocks
(`secret_id_bound_cidrs`, `token_bound_cidrs`, per OpenBao's own
AppRole API reference) — usable only for an identity with a stable
address.

## Decision

This table shows what each of the four AppRoles reaches, as this revision decided it, not what runs now.

| AppRole | Reaches | Does not reach |
| :--- | :--- | :--- |
| `cd-agent-deploy` | Read on `secret/data/hosts/*` and `secret/data/cloud_credentials/leaf/*`; `create` but not `update` on `secret/data/hosts/*` | `cloud_credentials/rotation/*` |
| `cd-agent-rotation` | Create, update and read on `secret/data/cloud_credentials/leaf/*` and `secret/data/cloud_credentials/rotation/*` | `secret/data/hosts/*` |
| `cd-agent-freshness` | Read on `secret/data/cloud_credentials/leaf/*`, `secret/data/cloud_credentials/rotation/*` and `secret/data/hosts/all/telegram/*` | Writing or rotating anything |
| `cd-agent-snapshot` | Read on `sys/storage/raft/snapshot` and six named paths under `secret/data/cloud_credentials/leaf/` | The rest of `leaf/*` |

Four AppRoles, all bound to `cd_agent`'s fixed LAN IP via
`secret_id_bound_cidrs` and `token_bound_cidrs`:

- `cd-agent-deploy` — read on `secret/data/hosts/*` and
  `secret/data/cloud_credentials/leaf/*`, plus `create` but not
  `update` on `secret/data/hosts/*`. The secrets play that opens every
  deploy and maintenance run generates and writes any generated secret
  that does not exist yet, which needs `create`; OpenBao requires
  `update` only to write a path that already exists
  ([KV v2 API](https://openbao.org/docs/api/secret/kv/kv-v2/)), so a
  compromised deploy job can add a new secret but not overwrite one. No
  access to `cloud_credentials/rotation/*` at all — it can't reach any
  master-tier credential.
- `cd-agent-rotation` — create/update (and read) on
  `secret/data/cloud_credentials/leaf/*` and
  `secret/data/cloud_credentials/rotation/*`. No access to
  `secret/data/hosts/*` — the rotation job has no business touching
  app secrets.
- `cd-agent-freshness` — read-only on
  `secret/data/cloud_credentials/leaf/*`,
  `secret/data/cloud_credentials/rotation/*` and
  `secret/data/hosts/all/telegram/*`. The freshness check reads the
  rotation-tier credentials to ask each provider when its keys expire,
  and the Telegram credentials ([ADR 0021 (Ownerless secret paths)](../0021-secret-path-layout-for-secrets-with-no-host-owner/revision-000.md))
  to send its alert, as the watcher in
  [ADR 0026 (High-value secret read alerts)](../0026-detecting-reads-of-high-value-secrets/revision-000.md)
  already does. It can read what rotation holds but cannot write or
  rotate anything, and rotation never needs the Telegram path.
- `cd-agent-snapshot` — read on `sys/storage/raft/snapshot` and on six
  named paths under `secret/data/cloud_credentials/leaf/`:
  `cloudflare-r2-openbao-snapshot-write-access-key`,
  `cloudflare-r2-openbao-snapshot-write-secret-key`,
  `backblaze-b2-openbao-snapshot-write-access-key`,
  `backblaze-b2-openbao-snapshot-write-secret-key`,
  `cloudflare-r2-account-id` and `backblaze-b2-region`. These are the
  paths `tools/openbao_utils/scripts/snapshot-push.sh` reads to save a
  snapshot and push it to R2 and B2. Naming each path, not `leaf/*`,
  keeps every other leaf out of reach of the one job whose purpose is
  to pull the whole database.

All four AppRoles live on the same host, so the CIDR bind separates
`cd_agent` from everything else on the network, not the jobs from each
other. Each job runs as its own Unix user ([ADR 0044 (CD agent trigger)](../0044-prod-automation-trigger-and-execution/revision-000-c.md)),
so a compromised job process cannot read another job's `secret_id`. The
AppRoles stay separate so the policies differ as well as the files;
root on the host can read all of them.

Each `cd_agent` job authenticates fresh per invocation: a
short-lived token per run, not one long-lived token held in memory
between runs. The `secret_id` is the credential that persists on
`cd_agent` (`secret_id_num_uses: 0`, no expiry), as a plain `0400` file
owned by that job's user. A single-use `secret_id` would mean
re-issuing it every run, which defeats the point of a durable bootstrap
secret for an always-on box. It carries the same on-disk exposure as
any other cached credential in this repo; the CIDR bind and narrow
policy limit its blast radius, not its use-count.

Each `secret_id` is generated once during `cd_agent`'s own provisioning
and delivered response-wrapped, unwrapped on `cd_agent` itself, so the
raw value is only ever written to its `0400` file. Until the
controller's AppRole is retired, the operator host requests the wrapped
value through `vault-bootstrap` ([ADR 0025 (Admin without root token)](../0025-admin-capability-without-a-standing-root-token/revision-000.md)),
the one identity whose policy grants `auth/approle/role/+/secret-id`
and none of `secret/data/*`; `controller`'s own policy has no
`auth/approle` capability. How the controller authenticates once its
AppRole is gone is [ADR 0047 (First-credential bootstrap)](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md)'s.

Once `cd-agent-deploy`/`cd-agent-rotation` are live and proven,
`controller`'s AppRole is deleted outright, not narrowed. From that
point, `controller` would hold no standing Vault credential at all —
any rare admin/debug/break-glass access uses a token generated on
demand by whoever already holds Vault access (e.g. during a restore
drill), narrowly scoped and short-lived, never persisted to disk.

## Consequences

- A compromised deploy job can plant a value for a generated secret that
  does not exist yet, which `controller`'s grant allows today too.
- The freshness role reads the R2 admin token's path, which the watcher
  in ADR 0026 alerts on for any read, so each weekly freshness run's
  alert names `cd-agent-freshness` as the role. That alert is accepted
  as the weekly signal that the check ran.
- The snapshot role downloads the whole raft database, sealed under a
  key that is not on `cd_agent`, and GPG-encrypts it again before it
  leaves; its protection rests on the unseal keys never being there.
- The snapshot job pushes with a native `rclone`, not the throwaway
  container the manual script uses. Access to the Docker socket is
  root-equivalent and would let its user read every other job's
  credentials ([ADR 0044 (CD agent trigger)](../0044-prod-automation-trigger-and-execution/revision-000-c.md)).
- Until the snapshot job exists, the manual script keeps using
  `controller`'s AppRole ([ADR 0019 (OpenBao offsite snapshot)](../0019-openbao-offsite-snapshot-path/revision-000.md)),
  so that AppRole cannot be deleted before this one is live.
- Token lifetime (`token_ttl`) per `cd_agent` invocation is a project
  decision, bounded below by the longest job run and kept short enough
  that a leaked token from one run doesn't outlive it by much.
- `secret_id` rotation cadence for `cd_agent`'s four AppRoles is a
  project decision too: re-running `cd_agent`'s own provisioning is the
  natural mechanism, matching this repo's human-attended pattern for
  cloud rotation-key bootstrap.
- If `cd_agent`'s LAN IP ever changes, every AppRole's CIDR bind needs
  updating — a manual step, not something the agent's own jobs could
  safely do (it would be the job editing its own trust boundary).
