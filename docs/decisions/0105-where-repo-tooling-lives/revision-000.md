---
id: ADR-0105
revision: 0
type: adr
title: Where repo tooling lives
short: Repo tooling location
solution: A root tools/ directory split by domain, with OpenBao utilities in tools/openbao_utils/ and only Ansible orchestration under ansible/scripts/
summary: Controller-side utilities live where their domain says, not where they happened to be written, and a script that drives playbooks is the only kind that stays under ansible/.
topic: repository-tooling
status: accepted
related: [ADR-0064, ADR-0104]
former_ids: [ADR-0031, ADR-0032]
---

# 0105. Where repo tooling lives

## Problem

Controller-side utilities sat where they happened to be written, not where their
domain says. The B2, OCI and R2 credential package held an OpenBao client that
was a different domain. Scripts for the secrets store sat loose at the top of
`ansible/` and duplicated that client, and a watcher sat in a third place. The
scatter let the same missing-timeout defect exist independently in two files, and
other scripts reached sideways into the credential package for generic helpers
that had nothing to do with credentials.

## Context

- The repository root holds `pyproject.toml`, and package resolution is manual
  `sys.path` and working-directory manipulation throughout (`[tool.uv]
  package = false`, no real Python packaging), so a `tools/` root shares it with
  no change.
- `r2_read_watcher.py` is hand-installed as a single file onto `security`'s system
  Python and referenced by no Dockerfile. It is never part of the `uv`-managed
  tree, and sharing code across that boundary would mean shipping a second file
  with a script whose point is staying one file.
- The test for whether a script belongs under `ansible/` is whether it drives
  playbooks or roles, not whether it runs around a deploy. Credential scripts are
  also sequenced around a deploy and live in `tools/`. `restore_all.py` calls
  `ansible-playbook` directly and `molecule-test-all.sh` is Molecule orchestration;
  the bootstrap, audit and two restore scripts drive no playbook.
- The two restore scripts ran as consecutive steps against the same backup
  directory, the second restoring what the first could not reach, with no stated
  reason for being two scripts.

## Decision

- **A root `tools/` directory, split by domain.** `tools/cloud_credentials/` holds
  B2, OCI and R2 credential minting, `tools/openbao_utils/` holds the OpenBao
  client and utilities, and `tools/utils/repo.py` holds generic repository
  navigation and SSH and certificate fetching helpers (`PROJECT_ROOT`,
  `SECRETS_DIR`, `INVENTORY_PATH`, `read_bootstrap_file()`, `main_domain()`,
  `security_ssh_target()`, `fetch_root_cert()`). `tools/openbao_utils/client.py`
  keeps only what is OpenBao-specific: `VAULT_KV_MOUNT`, `openbao_base_url()`,
  `vault_login()`, `vault_read()` and `vault_write()`. The package was first named
  `openbao_client` and became `openbao_utils` once it held executable scripts.
- **Scripts move by domain, with shorter names.** `bootstrap.py`, `audit.py`,
  `restore.py`, `dump.py` and `diff.py` live in `tools/openbao_utils/`. The two
  restore scripts are merged into `restore.py`, as two phases (registry-scoped
  restore, then the legacy cache keys) with one combined summary, and it does not
  strip backup content before writing it back to the secrets store, since
  stripping would corrupt a value with real leading or trailing whitespace.
  `restore_all.py` and `molecule-test-all.sh` live in `ansible/scripts/`.
- **Imports and invocation.** Each moved script imports in-process what it needs,
  as `cloud_credentials` does: `bootstrap.py` and `audit.py` use `client.py`'s
  primitives, `restore.py` and `dump.py` go through the credential package's
  higher-level API, and `diff.py` needs neither. The wrapper scripts under
  `docker/openbao/scripts/` import `security_ssh_target`, `main_domain` and
  `PROJECT_ROOT` from `tools/utils/repo.py`. `read_vault_path` and
  `write_vault_path` stay the credential package's own API. Every script in
  `tools/` is invoked as a module from `tools/`: `cd tools && python3 -m
  openbao_utils.bootstrap`.
- **The one exception to sharing `PROJECT_ROOT`.** `restore_all.py` keeps its own
  local definition, since it has no other dependency on `tools/`.
- **The watcher stays outside the shared client** and keeps its own copy.
- **A package name must not shadow an installed or standard-library module.** A
  `tools/secrets/` package would have shadowed Python's `secrets` once `tools/`
  was on `sys.path`, so each new package name is checked against both.

## Alternatives considered

- **Leave the layout as it was.** Cheapest, but the domain stays scattered and the
  next OpenBao script has no obvious home.
- **An `ansible/secrets/` package beside `ansible/cloud_credentials/`.** A smaller
  move, but it keeps non-Ansible standalone tooling under a name for Ansible.
- **Keep the secrets-store scripts in `ansible/` because they run around a deploy.**
  Tried first and dropped: sequencing around a deploy is not deploy orchestration,
  and the credential scripts already show it.

## Consequences

- One shared implementation replaces four, so the duplicated-defect failure cannot
  recur the same way.
- A move is not done until every caller is re-pointed and run; string-based mock
  patches name `openbao_utils.<module>`, and a script's `cd` and sibling-path
  assumptions change when it moves.
- A test fixture that replicates `restore_all.py`'s directory depth follows it.
- The CI trigger path for Python unit tests names `ansible/scripts/*.py`.
- The reinit runbook's two restore steps became one.

## Non-goals

- The Python client libraries each service uses, which
  [ADR 0104](../0104-which-client-library-each-external-service-uses/revision-000.md)
  decides.
- Where CI and documentation check code lives, which
  [ADR 0064](../0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md)
  decides within this layout.

## Reconsideration triggers

- A script that drives playbooks and one that does not need to share code.
- A new package would shadow an installed module, or `tools/` needs real packaging.
