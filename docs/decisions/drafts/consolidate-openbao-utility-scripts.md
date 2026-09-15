---
id: DRAFT-consolidate-openbao-utility-scripts
title: "Consolidate OpenBao utility scripts into tools/openbao_utils/, not ansible/scripts/"
type: draft-adr
status: decided
---

# Consolidate OpenBao utility scripts into tools/openbao_utils/, not ansible/scripts/

**Status:** Decided

## Context

Replaces this project's own earlier draft, "Move ansible/ root's
standalone Python scripts into ansible/scripts/" - no code was
written against it, so revising costs nothing. That draft's reasoning
("explicitly gated to the `ansible-playbook deploy.yaml` lifecycle"
therefore `ansible/`'s domain) doesn't actually hold up:
`cloud_credentials` scripts are *also* implicitly sequenced around a
deploy run (credentials need to exist before `backup_agent` can use
them) and correctly live in `tools/` anyway. Being sequenced around a
deploy isn't the same as being deploy orchestration. The real test:
does a script drive Ansible playbooks/roles, or is it a standalone
utility that happens to be part of the operator's workflow?

By that test, checked against each script directly, not assumed:
`restore_all.py` genuinely drives `ansible-playbook` (`subprocess.run`
calls it four times); `molecule-test-all.sh` is Ansible/Molecule test
orchestration. Both stay `ansible/`'s domain. `bootstrap_secrets.py`,
`audit_secrets.py`, `restore_hosts_scope_from_backup.py`, and
`restore_cloud_credentials_from_backup.py` drive no playbook at all -
they're Vault utilities that happen to run around the same lifecycle.
Confirmed `restore_all.py` has no direct dependency on any of the
other four (`grep` for each name in `restore_all.py`: zero matches) -
these five scripts are independent of each other, not a bundle that
has to move together.

Two more files turned out to belong in the same bucket, found by
reading their own docstrings rather than assuming their current
package name was accurate: `tools/cloud_credentials/dump_vault_to_file_cache.py`
explicitly covers *both* `cloud_credentials` keys and
`secrets_registry.yaml`'s `hosts/*` material - not cloud-credential-
specific at all - and `diff_vault_backups.py` has zero
`cloud_credentials`-touching code (confirmed: no import from
`cloud_credentials` anywhere in it), it's pure file comparison built
to consume what `dump_vault_to_file_cache.py` produces. Same
generic-thing-in-a-narrowly-named-package pattern
[ADR 0031](../0031-tools-secrets-package-split.md) exists to fix, one
level down.

`restore_hosts_scope_from_backup.py` and
`restore_cloud_credentials_from_backup.py` are confirmed run as
consecutive steps (5, 6) in `openbao-reinit-runbook.md`, against the
same backup directory, for the same purpose - step 6's own docstring
says it "restores what step 5 can't reach." No stated reason they're
separate scripts rather than one two-phase operation.

This revises one specific passage of already-accepted
[ADR 0031](../0031-tools-secrets-package-split.md) - not its
structural decision (the `tools/` root, split by domain, stands
unchanged), just its call on where these four specific scripts land.
ADR 0031 gets a short pointer note to here, not a rewrite.

Checked before naming anything, same diligence as the `tools/secrets`
rename: no installed dependency or stdlib module resolves
`openbao_utils`, and none plausibly would.

## Decision

`tools/openbao_client/` renamed to `tools/openbao_utils/` - once it
holds executable utility scripts alongside the shared client
primitives, "client" undersells what's there; "utils" matches
`cloud_credentials`'s own shape (a shared module plus the scripts that
use it, in one package).

Moves, with shorter names now that the package name carries the
"OpenBao" context (`openbao_utils.bootstrap_secrets` restates what
`openbao_utils.bootstrap` already says):

| From | To |
| :--- | :--- |
| `ansible/bootstrap_secrets.py` | `tools/openbao_utils/bootstrap.py` |
| `ansible/audit_secrets.py` | `tools/openbao_utils/audit.py` |
| `ansible/restore_hosts_scope_from_backup.py` + `ansible/restore_cloud_credentials_from_backup.py` | `tools/openbao_utils/restore.py` (merged) |
| `tools/cloud_credentials/dump_vault_to_file_cache.py` | `tools/openbao_utils/dump.py` |
| `tools/cloud_credentials/diff_vault_backups.py` | `tools/openbao_utils/diff.py` |
| `ansible/restore_all.py` | `ansible/scripts/restore_all.py` |
| `ansible/molecule-test-all.sh` | `ansible/scripts/molecule-test-all.sh` |

Each moved script keeps importing in-process whatever it actually
needs, matching `cloud_credentials`'s own established pattern rather
than inventing a uniform one: `bootstrap.py`/`audit.py` use
`client.py`'s bare primitives directly (they build their own
`hvac.Client` session); `restore.py`/`dump.py` go through
`cloud_credentials.cache`'s higher-level `read_vault_path`/
`write_vault_path` plus `LEGACY_CACHE_KEYS`, never touching `client.py`
at all; `diff.py` needs neither, unchanged. The `sys.path.insert`
dance every one of these currently does to reach `tools/` from outside
it disappears entirely - they're already inside `tools/` once moved.

`restore.py`'s merge: one script, two phases (registry-scoped restore
via `read_vault_path`/`write_vault_path`, then `LEGACY_CACHE_KEYS`
restore via each key's own module), one combined summary. Replaces
`openbao-reinit-runbook.md`'s steps 5 and 6 with one step.

Invocation convention becomes uniform across every `tools/`-resident
script: `cd tools && python3 -m openbao_utils.bootstrap`, matching
`cloud_credentials`'s own `python3 -m cloud_credentials.create_leaf_keys` -
no more mixing direct-file-path invocation
(`python3 ansible/bootstrap_secrets.py`) with module invocation
depending on which package a script happened to sit in.

Test files move and rename to match, mirroring
`tools/tests/cloud_credentials/`'s own convention:
`tools/tests/openbao_utils/{test_bootstrap,test_audit,test_restore,test_dump,test_diff}.py`.
The two restore test files merge into one, same as their sources.

## Consequences

- Real multi-file mechanical work, bigger in scope than the draft this
  replaces: a package rename (every importer's import line), five
  scripts renamed and relocated (one merged from two), two more moved
  out of `cloud_credentials`, and two moved into a much smaller
  `ansible/scripts/` than originally planned. Every doc/config
  reference to any of these scripts by their old name needs
  re-inventorying at execution time - the old draft's 16-file count
  doesn't carry over cleanly, since renames widen the search beyond
  path changes alone.
- `ansible/scripts/` ends up holding two files
  (`restore_all.py`/`molecule-test-all.sh`), not five - a much smaller
  move than originally scoped, landing squarely on genuine
  Ansible-orchestration code only.
- `openbao-reinit-runbook.md` loses a step (5 and 6 become one).
- ADR 0031 keeps its structural decision intact; only its specific
  call on these four scripts is revised here, with a pointer added
  there rather than an edit to its own text.

Tracked in
[`consolidate-openbao-utility-scripts.md`](../../projects/consolidate-openbao-utility-scripts.md)
once someone picks this up.
