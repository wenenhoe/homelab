---
id: DRAFT-ansible-root-scripts-into-scripts-dir
title: "Move ansible/ root's standalone Python scripts into ansible/scripts/"
type: draft-adr
status: decided
---

# Move ansible/ root's standalone Python scripts into ansible/scripts/

**Status:** Decided

## Context

`ansible/`'s root currently mixes two different kinds of thing: real
top-level tooling config (`ansible.cfg`, `requirements.yml`,
`molecule-test-all.sh`) and five loose, standalone Python scripts
(`bootstrap_secrets.py`, `audit_secrets.py`, `restore_all.py`,
`restore_cloud_credentials_from_backup.py`,
`restore_hosts_scope_from_backup.py`) that have nothing to do with
Ansible's own config surface - they're plain executable Python,
invoked directly (`python3 ansible/bootstrap_secrets.py`), not through
`ansible-playbook`. `tools-secrets-package-split.md` already
established these four (`audit_secrets.py` aside) are genuinely
`ansible/`'s domain, not `tools/`'s - explicitly gated to the
`ansible-playbook deploy.yaml` lifecycle. This decision is narrower:
given they belong in `ansible/`, should they sit loose at its root, or
in their own subdirectory the way `cloud_credentials` (now
`tools/cloud_credentials/`) and the test suite (`ansible/tests/`)
already do?

Confirmed by direct inventory, not assumed: 16 files reference these
five scripts by path or invocation - `README.md`,
`secrets_registry.yaml`'s header comment, `rotate-secret.yaml`,
`ensure_secret.yaml`, `restore_discovery`'s molecule `converge.yml`,
and ten docs (`secrets.md`, `restore.md`, `uptime-kuma.md`,
`secrets-rotation.md`, `cloud-credential-creation.md`,
`deployment-flow.md`, `openbao-reinit-runbook.md`, `beszel.md`,
`telegram-notifications.md`, and this project's own
`0030-openbao-hvac-paramiko-clients.md`/
`0031-tools-secrets-package-split.md` references). Each has
a matching test file already living in `ansible/tests/`
(`test_bootstrap_secrets.py`, `test_audit_secrets.py`,
`test_restore_all.py`,
`test_restore_cloud_credentials_from_backup.py`,
`test_restore_hosts_scope_from_backup.py`) - real, mechanical scope
comparable to `tools-secrets-package-split.md`'s Stage 2 move, not a
one-line rename.

## Decision

New `ansible/scripts/` directory, holding all five scripts as plain
files (not a package - none of them import each other, so there's no
need for an `__init__.py` or shared namespace, matching how
`ansible/tests/` itself is a plain directory, not a package). Every
`python3 ansible/bootstrap_secrets.py`-style invocation becomes
`python3 ansible/scripts/bootstrap_secrets.py`. Confirmed live (every
`Path(__file__)` usage across all five files checked directly, not
assumed) exactly two patterns need their parent count bumped by one
to account for the new nesting level: the `sys.path.insert(0,
str(Path(__file__).resolve().parent.parent / "tools"))` line present
in four of the five files, and `restore_all.py`'s/`audit_secrets.py`'s
own locally-defined `PROJECT_ROOT = Path(__file__).resolve().parent.parent`
(`bootstrap_secrets.py`'s and `restore_cloud_credentials_from_backup.py`'s
equivalent already comes from `openbao_client.client`'s own `PROJECT_ROOT`,
anchored to that module's own location, unaffected by these five
files moving). Test files stay in `ansible/tests/` where they already
are - matching `cloud_credentials`'s own pattern of
`tools/cloud_credentials/` code paired with
`tools/tests/cloud_credentials/` tests, this would suggest
`ansible/tests/scripts/`, but these five tests already sit flat in
`ansible/tests/` importing their target via `sys.path`, not nested in
a subdirectory mirroring the source - left as-is rather than moved
too, since nothing about their own organization is actually confusing
today, only the source scripts' location is.

Considered and rejected: per-lifecycle subdirectories
(`ansible/bootstrap/`, `ansible/restore/`, `ansible/audit/`) - more
granular, but five files split across three near-empty directories
reads as more organized than it actually is; a single `ansible/scripts/`
directly answers "where do I look for a standalone script" without
requiring the reader to already know which lifecycle bucket a given
script falls into.

## Consequences

- 16 files get a mechanical path update in the same patch as the move
  - real work, not a one-liner, but the same shape already proven out
    in `tools-secrets-package-split.md`'s Stage 2.
- `ansible/`'s root becomes just tooling config
  (`ansible.cfg`/`requirements.yml`/`molecule-test-all.sh`) plus real
  directories (`inventory/`, `roles/`, `playbooks/`, `tests/`,
  `molecule-coverage/`, `files/`, `scripts/`) - no more loose
  standalone scripts to explain away.
- `ansible/tests/`'s own five test files stay exactly where they are,
  now importing their target from `ansible/scripts/` instead of
  `ansible/` directly - a one-line `sys.path`/import-path change each,
  not a file move.

Tracked in
[`ansible-root-scripts-into-scripts-dir.md`](../../projects/ansible-root-scripts-into-scripts-dir.md)
once someone picks this up.
