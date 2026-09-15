---
id: PROJ-consolidate-openbao-utility-scripts
title: "Consolidate OpenBao utility scripts into tools/openbao_utils/"
type: project
status: in-progress
summary: "Rename tools/openbao_client/ to tools/openbao_utils/; move and rename bootstrap_secrets.py, audit_secrets.py, the two restore_*_from_backup.py scripts (merged), dump_vault_to_file_cache.py, and diff_vault_backups.py into it; move restore_all.py and molecule-test-all.sh into a new ansible/scripts/."
---

# Consolidate OpenBao utility scripts into tools/openbao_utils/

**Status:** In progress

Renames `tools/openbao_client/` to `tools/openbao_utils/`, moves five
scripts into it (merging two into one, shortening every name now that
the package supplies context), pulls two more out of
`tools/cloud_credentials/` that never belonged there, and gives
`ansible/`'s remaining genuine orchestration scripts a home in a new
`ansible/scripts/`. Design lives in
[`consolidate-openbao-utility-scripts.md`](../decisions/drafts/consolidate-openbao-utility-scripts.md);
this doc tracks build status only. Replaces this project's own earlier
"ansible-root-scripts-into-scripts-dir" project - never started, no
code written against it.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | Rename `tools/openbao_client/` → `tools/openbao_utils/` | Done |
| 2 | Move + rename `bootstrap_secrets.py` → `openbao_utils/bootstrap.py` | Not started |
| 3 | Move + rename `audit_secrets.py` → `openbao_utils/audit.py` | Not started |
| 4 | Merge both restore scripts → `openbao_utils/restore.py` | Not started |
| 5 | Move + rename `dump_vault_to_file_cache.py`/`diff_vault_backups.py` | Not started |
| 6 | Move `restore_all.py`/`molecule-test-all.sh` → `ansible/scripts/` | Not started |
| 7 | Add ADR 0031's pointer note; re-inventory and fix every reference | Not started |

## Stage detail

### Stage 1 — Rename the package

Done. Every importer of `openbao_utils.client` updated:
`tools/cloud_credentials/cache.py`, `ansible/bootstrap_secrets.py`,
`ansible/restore_hosts_scope_from_backup.py`'s stale comment,
`docker/openbao/scripts/bao-login-from-controller.sh`'s stale comment
(`bao-from-controller.sh` had none), and every test file - a single
bulk substitution across all of them, since "openbao_client" never
appears as a substring of anything else in this codebase (confirmed by
grepping before touching anything). Verified live, not just under
mocks: direct `openbao_utils.client` import, the full `cache.scoped()`
chain, `bootstrap_secrets.py`, and `restore_hosts_scope_from_backup.py`
all re-run end to end.

Found and fixed a real, pre-existing gap while touching this file's CI
trigger paths: `tools/openbao_utils/**` (then `openbao_client`) and
`tools/utils/**` were never added as their own
`python_unit_tests` trigger paths since Stages 3/6 created them -
only incidentally covered if a paired test file also changed in the
same PR. Added both, and updated `docs/ci.md`'s description to match.

### Stage 4 — Merge the restore scripts

Two phases in one script: registry-scoped restore (via
`cloud_credentials.cache`'s `read_vault_path`/`write_vault_path`,
today's `restore_hosts_scope_from_backup.py`) then `LEGACY_CACHE_KEYS`
restore (via each key's own module, today's
`restore_cloud_credentials_from_backup.py`), one combined summary
covering both. `openbao-reinit-runbook.md`'s steps 5 and 6 collapse
into one. Test files merge the same way.

### Stage 7 — References and the ADR pointer

The real work. Every doc/config reference to any of these scripts by
their *old* name needs finding fresh - the predecessor project's
16-file inventory doesn't carry over cleanly, since renames (not just
moves) widen what "references this script" means. Add a short pointer
note to [ADR 0031](../decisions/0031-tools-secrets-package-split.md)
noting this project revises its specific call on where these scripts
land, without editing 0031's own Decision text.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes) - run
before deleting this doc once every stage is Done.

- [ ] Every `Done` stage's rationale exists as a real ADR, or plainly
      didn't need one.
- [ ] Every `Done` stage's current behavior is in a topic doc.
- [ ] Every open item is resolved-and-promoted or moved to where it
      belongs next.
- [ ] Every cross-reference into this doc elsewhere in the repo is
      updated or removed.
