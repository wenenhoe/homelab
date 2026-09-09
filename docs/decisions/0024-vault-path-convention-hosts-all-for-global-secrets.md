# 0024. Vault path convention: `hosts/<host>/*` mirrors `host_vars`, `hosts/all/<concern>/*` mirrors `group_vars/all`

**Status:** Accepted

## Context

[0022](0022-approle-policy-structure-two-eras.md)'s Era A policy grants
`controller` read/write on `secret/data/hosts/*`, describing it as
"mirroring the `security`/`services`/`storage`/`play` `host_vars`
split." But `secrets_registry.yaml` also holds secrets with no single
host owner — `step-ca-provisioner-password`, `digitalocean-api-key`,
the `telegram-*` family, `beszel-hub-key`/`beszel-agent-token` — every
one referenced from `group_vars/all/main.yaml`, not any `host_vars/*.yaml`
file. The Accepted policy has no path for these: they aren't
`cloud_credentials/*` (a different consumer, different lifecycle — see
below), and forcing them under one specific host's namespace would
misrepresent them and contradict 0022's own stated rationale for that
path.

The real question this stage needs answered before writing a single
secret to Vault: does this get a new top-level path (parity with
`cloud_credentials/{leaf,rotation}`), or does it live inside the
already-Accepted `hosts/*` grant?

**Who actually reads these secrets settles it.** `cloud_credentials/leaf`
and `.../rotation` earned separate top-level paths anticipating a
consumer `hosts/*` doesn't have: a planned future split between a
deploy-focused identity (read-only, leaf credentials only) and a
rotation-focused identity (read/write, both leaf and rotation), so
that whichever job runs deploys can't reach master-tier credentials.
That split doesn't exist yet — today one identity (`controller`) reads
all of it under one broad policy — but the taxonomy is already shaped
for it. Global app-config secrets have no such planned consumer. Every
one of them is read by `deploy.yaml`'s config-rendering plays exactly
the way a host-scoped secret is (caddy needs `digitalocean-api-key`
regardless of which host runs it; diun needs the `telegram-*` values
the same way). `controller`'s existing broad grant on `hosts/*`
already covers this today; if a future deploy-only identity is ever
split out, it would need the same read access to `hosts/*` these
global secrets already live under. Nothing today schedules rotation
for a Telegram token or the DO key — which secrets beyond cloud
credentials ever get rotation automation remains unscoped.
Inventing a parallel top-level path now would be designing against a
consumer that doesn't exist and isn't planned; if a specific global
secret ever needs that consumer, that's a one-time path migration for
that one secret, not a reason to fork the whole taxonomy today.

## Decision

`group_vars/all/main.yaml` is treated as a pseudo-host, `all` —
Ansible's own reserved group name for exactly this file — under the
same `secret/data/hosts/*` prefix 0022 already grants:

```
secret/data/hosts/<host>/<key>            # host_vars/<host>.yaml secrets
secret/data/hosts/all/<concern>/<key>     # group_vars/all/main.yaml secrets
```

Sub-grouped by consumer/concern under `all` (`telegram`, `beszel`,
`caddy-acme`, `step-ca`, ...) — organizationally the same shape
`cloud_credentials/{leaf,rotation}` uses, but every one of these paths
still resolves under the single wildcard `secret/data/hosts/*`, so
`controller.hcl` needs no edit for this stage. Each `secrets_registry.yaml`
entry that moves to Vault declares its own `vault_scope` (the directory
prefix; the registry key itself is the final path segment) —
explicit per entry, not inferred from which YAML file happens to
reference it today, so a future reorganization of `host_vars`/`main.yaml`
doesn't silently relocate a secret in Vault.

## Consequences

- No `controller.hcl` change, no re-review of an Accepted stage-3
  artifact — this stage's Vault writes fall entirely inside scope
  already granted and proven working (`openbao-auth.md`'s stage-3
  runbook, step 6).
- If a global secret's consumer ever changes such that it needs
  `cd-agent-rotation`-style access (denied `hosts/*` by design) or any
  other narrower scope, that secret's `vault_scope` moves to a new
  top-level path and its ACL grant is added then — a small, contained
  migration for that one secret (write new path, flip its
  `secrets_registry.yaml` `vault_scope`, delete the old path), not a
  taxonomy redesign, since `vault_scope` is already the single source of
  truth `ensure_secret.yaml` reads — no code change needed to move a
  secret, only registry data.
- A **future** role scoped to "every host's secrets, but explicitly not
  any global concern" (or the reverse) isn't automatically excluded by
  nesting `all` under `hosts/*` — its policy adds one explicit `deny`
  stanza on `hosts/all/*` alongside its `hosts/*` grant (Vault's policy
  merge rules let a more-specific path override a less-specific one).
  One extra line, in a policy that doesn't exist yet, for a shape
  nothing in the current roadmap needs — accepted as cheaper than
  splitting the taxonomy today for a consumer that isn't built.
- New secrets need a `vault_scope` decision at registry-entry time: one
  of the four real hosts, or `all/<concern>`. This is a naming
  convention future contributors need to follow, not something
  mechanically derivable — flagged in `secrets_registry.yaml`'s own
  header comment.
- Full current mapping lives in `secrets_registry.yaml` itself (each
  entry's `vault_scope` field) and in [`secrets.md`](../secrets.md) —
  not duplicated here.
