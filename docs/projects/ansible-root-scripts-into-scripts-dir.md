---
id: PROJ-ansible-root-scripts-into-scripts-dir
title: "Move ansible/ root's standalone scripts into ansible/scripts/"
type: project
status: not-started
summary: "Move bootstrap_secrets.py, audit_secrets.py, restore_all.py, restore_cloud_credentials_from_backup.py, and restore_hosts_scope_from_backup.py from ansible/'s root into ansible/scripts/, updating the 16 files that reference them."
---

# Move ansible/ root's standalone scripts into ansible/scripts/

**Status:** Not started

Moves five loose standalone Python scripts off `ansible/`'s root into
`ansible/scripts/`, leaving the root to tooling config
(`ansible.cfg`/`requirements.yml`/`molecule-test-all.sh`) and real
directories only. Design lives in
[`ansible-root-scripts-into-scripts-dir.md`](../decisions/drafts/ansible-root-scripts-into-scripts-dir.md);
this doc tracks build status only.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | Move the five scripts; fix their own internal `Path(__file__)` depth | Not started |
| 2 | Update the 16 referencing files (docs, playbooks, CI-adjacent config) | Not started |
| 3 | Re-point `ansible/tests/`'s five test files at the new location | Not started |

## Stage detail

### Stage 1 — Move the scripts

`git mv` each of `bootstrap_secrets.py`/`audit_secrets.py`/
`restore_all.py`/`restore_cloud_credentials_from_backup.py`/
`restore_hosts_scope_from_backup.py` into `ansible/scripts/`. Two
`Path(__file__)`-based patterns need their parent count bumped by one,
confirmed live in the draft's Decision - the `sys.path.insert` line
reaching `tools/` (four of the five files), and `restore_all.py`'s/
`audit_secrets.py`'s own locally-defined `PROJECT_ROOT` (the other
two files already get `PROJECT_ROOT` from `openbao_client.client`,
unaffected by this move).

### Stage 2 — Update referencing files

The real work - 16 files confirmed by direct inventory in the draft's
Context: `README.md`, `secrets_registry.yaml`'s header comment,
`rotate-secret.yaml`, `ensure_secret.yaml`, `restore_discovery`'s
molecule `converge.yml`, and ten docs. Same shape as
`tools-secrets-package-split.md`'s Stage 2, at smaller scale.

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
