# 0027. Re-init OpenBao now, with a standing narrow `vault-bootstrap` AppRole, instead of deferring to stage 6

**Status:** Accepted

## Context

[ADR 0026](0026-openbao-audit-device-and-r2-per-read-watcher.md) requires
a fourth Vault identity (the R2 per-read watcher's own AppRole).
Creating any new AppRole needs a token with `create`/`update` on
`sys/policies/acl/*` and `auth/approle/role/*`. `controller`'s policy
([`controller.hcl`](../../docker/openbao/policies/controller.hcl))
grants neither, and the only token that ever could -
the initial root token - was deliberately revoked at the end of
[`openbao-auth.md`](../openbao-auth.md)'s stage 3 runbook. No live
credential in this Vault can currently create a new AppRole.

Four candidates were on the table
([`openbao-migration-roadmap.md`](../openbao-migration-roadmap.md)'s
Open items):

1. **Never fully revoke root.** Rejected - reopens exactly the standing
   privileged credential `openbao-auth.md` was written to eliminate.
2. **A narrow sudo/policy-admin grant before revoking.**
3. **Defer to a full re-init at the roadmap's stage-6 cutover.**
4. **Confirm OpenBao's `-recovery` server mode as a way back to root.**

Option 4 is ruled out on the merits, not left untested: OpenBao's own
docs describe recovery mode as granting a token scoped to `sys/raw`
for direct storage repair, with none of the normal subsystems
(including the `approle` auth method and the `secret/` KV mount)
running - there is no path from a recovery token to writing a policy
or an AppRole role. Separately, `operator generate-root` on 2.6.x now
calls the *authenticated* `/sys/generate-root-token` endpoints, replacing
the old unauthenticated ones - so even a normal root-token regeneration
needs an already-capable token, not Shamir shares alone. This also
explains the roadmap's previously-unexplained 403 against `controller`'s
token on that exact endpoint.

Investigating option 3 surfaced two further findings, neither obvious
going in:

- A **snapshot restore** (`openbao-backup-restore.md`'s proven drill)
  reproduces the source snapshot's entire barrier/keyring/ACL state,
  including whatever root-token status it was backed up with. Since
  every snapshot since stage 3 was taken with root already revoked,
  restoring one would reproduce this exact problem, not fix it. Only a
  genuine fresh `bao operator init` - discarding the old raft dataset
  entirely - produces a new keyring and a usable root token.
- A fresh init means an **empty** Vault. `ensure_secret.yaml`'s
  generate-once-if-missing logic would see nothing at any
  `secret/data/hosts/*` path and mint new random values for this
  registry's 17 `hex`/`uuid4` entries on the next `deploy.yaml` run -
  silently invalidating already-deployed state (lldap's live JWT
  secret, SeaweedFS keys `cloud_sync`/`backup_agent` currently
  authenticate with, etc.). Every existing value has to be restored
  before any `deploy.yaml` run touches the fresh Vault.

Doing this now, rather than waiting for stage 6, is also when it's
actually needed: stage 5 cannot finish without a way to create new
AppRoles, and a live audit of Vault state
([`dump_vault_to_file_cache.py`](../../ansible/cloud_credentials/dump_vault_to_file_cache.py))
found `_oci-leaf-user-ocid-{read,write}` duplicated under
`cloud_credentials/leaf/` as well as its correct `rotation/` home - a
stale leftover from an earlier version of the migration mapping,
harmless (values match, nothing reads the `leaf/` copy) but also
un-removable today, since `controller`'s policy has never had `delete`
on that path either.

## Decision

A genuine re-init now, combining options 2 and 3: fresh keys, plus a
standing narrow AppRole this time instead of ending Era A with zero
admin-capable credential again.

1. Full backup first (`dump_vault_to_file_cache.py`) - already run.
2. Fresh `bao operator init -key-shares=3 -key-threshold=2`
   ([`openbao.md`](../openbao.md)'s existing convention) on `security`,
   discarding the old raft dataset. New Shamir shares and root token,
   handled with the same offline discipline as the original bundle -
   this fully supersedes the old one, which becomes useless the moment
   the raft dataset is gone.
3. Recreate KV v2, `approle`, and `controller`'s AppRole exactly per
   `openbao-auth.md`'s existing runbook, unchanged.
4. Create `vault-bootstrap` from the new
   [`vault-bootstrap.hcl`](../../docker/openbao/policies/vault-bootstrap.hcl):
   `create`/`update` on `sys/policies/acl/*` and `auth/approle/role/*`
   only - no `secret/data/*` access, no standing `sudo` on
   `sys/generate-root-token/*`. Cached with the same offline handling
   as the Shamir shares, never in `ansible/files/secrets/`.
5. Restore every `hosts/*`-scoped secret from the backup
   (`restore_hosts_scope_from_backup.py`) **before** any `deploy.yaml`
   run against the fresh Vault - the step that prevents the hex/uuid4
   regeneration problem above.
6. Restore `cloud_credentials` leaf/rotation material: copy the
   backup's cloud_credentials-covered files over the stale copies in
   `ansible/files/secrets/`, then re-run the existing
   `migrate_legacy_cache_to_vault.py` unmodified. The
   `_oci-leaf-user-ocid-*` duplicate at `leaf/` is not recreated - it
   was never read from there, so nothing regresses by leaving it
   behind.
7. Provision the R2 watcher's own AppRole (ADR 0026) using
   `vault-bootstrap` - the step that actually finishes stage 5.
8. Revoke root again, same as stage 3's own last step. This time it's
   not a dead end: see
   [`openbao-vault-bootstrap.md`](../openbao-vault-bootstrap.md) for
   how `vault-bootstrap` bootstraps a fresh root token on demand if
   ever genuinely needed, without a second re-init.

## Consequences

- A second one-time restore tool now exists
  (`restore_hosts_scope_from_backup.py`), deliberately separate from
  `migrate_legacy_cache_to_vault.py` - different source-of-truth
  convention (`secrets_registry.yaml`'s `vault_scope` vs.
  `_legacy_cache_keys.py`'s `LEGACY_CACHE_KEYS`), not worth merging
  into one.
- `vault-bootstrap`'s `secret_id` is now this repo's actual
  root-recovery mechanism, not a convenience credential - it needs the
  same offline discipline as the Shamir shares, spelled out in
  [`openbao-vault-bootstrap.md`](../openbao-vault-bootstrap.md) rather
  than treated as another cached AppRole.
- Every consumer of OpenBao (`controller`, `snapshot-push.sh`,
  `check_freshness.py`, `create_leaf_keys.py`/`create_rotation_keys.py`)
  is unusable for the duration of the runbook - real downtime,
  schedulable at will in a homelab, but not zero.
- Track B's future `cd-agent-deploy`/`cd-agent-rotation` AppRoles
  ([ADR 0022](0022-approle-policy-structure-two-eras.md)) get
  provisioned through `vault-bootstrap` too, not through a repeat of
  this gap.
- Options 1 and 4 from the roadmap's open item are resolved by this
  ADR: 1 rejected outright, 4 ruled out on OpenBao's own documented
  behavior rather than left as a live spike.
