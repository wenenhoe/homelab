---
id: ADR-0032
title: "Consolidate OpenBao utility scripts into tools/openbao_utils/, not ansible/scripts/"
type: adr
status: accepted
---

# 0032. Consolidate OpenBao utility scripts into tools/openbao_utils/, not ansible/scripts/

**Status:** Accepted

## Context

Revises one specific passage of already-accepted
[ADR 0031](0031-tools-secrets-package-split.md) - not its structural
decision (the `tools/` root, split by domain, stands unchanged), just
its call that `bootstrap_secrets.py`, `audit_secrets.py`, and the two
`restore_*_from_backup.py` scripts should stay in `ansible/` because
they're "gated to the `ansible-playbook deploy.yaml` lifecycle."
That reasoning doesn't actually hold up: `cloud_credentials` scripts
are *also* implicitly sequenced around a deploy run (credentials need
to exist before `backup_agent` can use them) and correctly live in
`tools/` anyway. Being sequenced around a deploy isn't the same as
being deploy orchestration. The real test: does a script drive
Ansible playbooks/roles, or is it a standalone utility that happens
to run around the same lifecycle?

By that test, checked against each script directly, not assumed:
`restore_all.py` genuinely drives `ansible-playbook` (`subprocess.run`
calls it four times); `molecule-test-all.sh` is Ansible/Molecule test
orchestration. Both stay `ansible/`'s domain. `bootstrap_secrets.py`,
`audit_secrets.py`, and both restore scripts drive no playbook at
all - they're Vault utilities. Confirmed `restore_all.py` has no
direct dependency on any of the other four (zero `grep` matches) -
these five scripts are independent of each other, not a bundle.

Two more files turned out to belong in the same bucket, found by
reading their own docstrings rather than trusting their package name:
`dump_vault_to_file_cache.py` explicitly covers both `cloud_credentials`
keys and `secrets_registry.yaml`'s `hosts/*` material - not
cloud-credential-specific at all - and `diff_vault_backups.py` had
zero `cloud_credentials`-touching code, pure file comparison. Same
generic-thing-in-a-narrowly-named-package pattern ADR 0031 exists to
fix, one level down.

The two restore scripts were confirmed run as consecutive steps (5,
6) in `openbao-reinit-runbook.md`, against the same backup directory,
for the same purpose - step 6's own docstring said it "restores what
step 5 can't reach." No stated reason they were separate scripts
rather than one two-phase operation.

Checked before naming anything, same diligence as the earlier
`tools/secrets` rename: no installed dependency or stdlib module
resolves `openbao_utils`.

## Decision

`tools/openbao_client/` renamed to `tools/openbao_utils/` - once it
holds executable scripts alongside the shared client primitives,
"client" undersold what's there; "utils" matches `cloud_credentials`'s
own shape. Moved, with shorter names now that the package name
carries the "OpenBao" context:

| From | To |
| :--- | :--- |
| `ansible/bootstrap_secrets.py` | `tools/openbao_utils/bootstrap.py` |
| `ansible/audit_secrets.py` | `tools/openbao_utils/audit.py` |
| `ansible/restore_hosts_scope_from_backup.py` + `ansible/restore_cloud_credentials_from_backup.py` | `tools/openbao_utils/restore.py` (merged) |
| `tools/cloud_credentials/dump_vault_to_file_cache.py` | `tools/openbao_utils/dump.py` |
| `tools/cloud_credentials/diff_vault_backups.py` | `tools/openbao_utils/diff.py` |
| `ansible/restore_all.py` | `ansible/scripts/restore_all.py` |
| `ansible/molecule-test-all.sh` | `ansible/scripts/molecule-test-all.sh` |

Each moved script imports in-process whatever it actually needs,
matching `cloud_credentials`'s own pattern rather than a uniform one:
`bootstrap.py`/`audit.py` use `client.py`'s bare primitives directly;
`restore.py`/`dump.py` go through `cloud_credentials.cache`'s
higher-level API plus `LEGACY_CACHE_KEYS`, never touching `client.py`;
`diff.py` needs neither. `restore_all.py` kept its own local
`PROJECT_ROOT` rather than importing `tools/utils/repo.py`'s - it has
zero other dependency on `tools/`, and importing one just for this
constant would work against the reasoning that keeps the file itself
out of `tools/`. This closes ADR 0031's last open `PROJECT_ROOT` item:
`bootstrap.py`, `audit.py`, `dump.py`, and `restore.py` all import it
from `tools/utils/repo.py` now instead of each redefining it locally;
`cache.py` turned out not to need it at all once `dump.py` was its
only reason to re-export it - removed entirely, confirmed dead by
grepping every remaining importer first. `restore_all.py`'s staying
local is the one deliberate exception, not an oversight.

`restore.py`'s merge is two phases in one script - registry-scoped
restore, then `LEGACY_CACHE_KEYS` restore - sharing one combined
summary, replacing `openbao-reinit-runbook.md`'s steps 5 and 6 with
one step. A real behavioral bug surfaced on merge: the two originals
disagreed on whether to strip backup content before writing it back
to Vault. `dump_vault_to_file_cache.py`'s own write side
(`path.write_text(value)`, no added whitespace) settled it - the
non-stripping behavior is correct, since stripping would silently
corrupt any value with genuine leading/trailing whitespace.

Invocation is now uniform across every `tools/`-resident script:
`cd tools && python3 -m openbao_utils.bootstrap`, matching
`cloud_credentials`'s own convention - no more mixing direct-file-path
invocation with module invocation depending on which package a script
happened to sit in.

## Consequences

- Two real, would-have-shipped bugs caught by actually running things
  post-move, not by trusting a mechanical rename: string-based
  `@patch("bootstrap.X")`/`@patch("audit.X")` test patches would have
  silently failed, since those names are only importable as
  `openbao_utils.bootstrap`/`openbao_utils.audit`, not bare top-level
  modules. And `molecule-test-all.sh`'s own `cd "$(dirname
  "${BASH_SOURCE[0]}")"` plus its `roles/*/molecule` sibling-path
  assumption would have silently pointed at the wrong directory once
  moved into `ansible/scripts/` - fixed by adjusting the `cd` target
  rather than every internal path.
- One genuinely significant test-fixture dependency, found and fixed
  together: `restore_discovery`'s own molecule scenario deliberately
  replicates `restore_all.py`'s exact directory depth in a sandbox, to
  exercise its real `PROJECT_ROOT`-relative logic. Verified by
  directly simulating that sandbox layout that the fix actually works,
  not just that it looked plausible.
- A live, real CI gap found in passing: `pr-checks.yml`'s
  `python_unit_tests` trigger path (`ansible/*.py`) silently stopped
  matching anything once every script left `ansible/`'s root - fixed
  to `ansible/scripts/*.py`, alongside a pre-existing stale comment
  claiming `restore_all.py` "has no test yet" (it does, 18 tests).
- `ansible/scripts/` ends up holding two files, not five - landing
  squarely on genuine Ansible-orchestration code only, once the
  domain test above was applied to each script individually rather
  than as a bundle.
- `openbao-reinit-runbook.md` lost a step (5 and 6 became one); every
  downstream step renumbered, and every cross-reference to a step
  number - within that file and in two others - updated to match.
