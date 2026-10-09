---
id: PROJ-vault-secret-module
title: "Vault Secret Module"
type: project
status: building
blocked: false
summary: "Replace process_vault_secrets.yaml's five-stage, index-correlated task sequence with one ensure_vault_secret module."
decision: ADR-0067/0
allowed_paths:
  - ansible/ansible.cfg
  - ansible/module_utils/openbao_kv.py
  - ansible/roles/secrets/library/ensure_vault_secret.py
  - ansible/roles/secrets/tasks/ensure_secret.yaml
  - ansible/roles/secrets/tasks/process_vault_secrets.yaml
  - ansible/roles/secrets/molecule/vault_backed/**
  - ansible/molecule-coverage/thresholds.yaml
  - ansible/tests/test_openbao_kv.py
  - ansible/tests/test_ensure_vault_secret.py
  - ansible/tests/test_secrets_module_no_log.py
  - pyproject.toml
  - docs/topics/secrets/secrets.md
  - docs/topics/engineering/molecule-testing.md
  - .github/detect-changes-filters.yml
  - tools/ci/scope/molecule_scope.py
  - tools/tests/ci/scope/test_molecule_scope.py
  - tools/tests/ci/test_layout.py
  - docs/topics/engineering/ci/change-scoping.md
  - ansible/roles/secrets/tasks/read_vault_kv.yaml
  - ansible/roles/secrets/tasks/generate_vault_value.yaml
  - docs/topics/secrets/openbao-cd-agent-approles.md
---

# Vault Secret Module

Replaces the read/generate/write/reread/store sequence in
`secrets/tasks/process_vault_secrets.yaml` with one custom module called
once per Vault-backed, generated secret. Staged so the module and its
shared client code are proven against a real OpenBao target before
`process_vault_secrets.yaml` is touched.

## Scope

`ansible/module_utils/openbao_kv.py`, the `ensure_vault_secret` module in
the `secrets` role's `library/`, `ansible/ansible.cfg`'s `module_utils`
setting, the role's `ensure_secret.yaml` and `process_vault_secrets.yaml`,
the `vault_backed` Molecule scenario, the tests for the module and for
`no_log` coverage under `ansible/tests/`, the test import roots in
`pyproject.toml`, the `secrets` role's coverage threshold, the two
topic docs that describe the module and its test target, and the CI change
scoping that has to know where the module and its shared code live
(`.github/detect-changes-filters.yml`, `tools/ci/scope/molecule_scope.py`,
their tests and `change-scoping.md`), and the files that name the code this
project deletes or changes the callers of: the two task files `rotate-secret.yaml`
shares with `ensure_secret.yaml` (comments only) and the CD agent's AppRole doc.
Not in scope: the manual/
`controller_file` path, `vault_login.yaml`'s AppRole login,
`tools/openbao_utils/client.py`, and `rotate-secret.yaml` (single-secret,
update-not-create, a different operation from this module's create-only
path).

## Decision

Implements
[ADR 0067 (Vault-backed secret module)](../decisions/0067-where-the-code-that-generates-and-stores-a-vault-backed-secret-lives/revision-000.md),
`approved`. The spike behind it is done.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | `ansible/module_utils/openbao_kv.py` and the `ensure_vault_secret` module, with unit tests | Done | Unit tests cover read-existing, generate-hex, generate-uuid4, and the `InvalidRequest` conflict-and-reread path against a mocked `hvac.Client`; the returned value is the real one, not a redaction marker, and `vault_token` is declared `no_log` |
| 2 | `vault_backed` Molecule scenario: add a create-race case | In progress | Two concurrent `ensure_vault_secret` calls for the same not-yet-existing secret against a real OpenBao test target resolve to the same value, one `changed: true` and one not; a call in a `no_log: true` task under `-vvv` prints neither the generated nor the reused value, and its registered value is the real one |
| 3 | Cut `process_vault_secrets.yaml` over to the module | In progress | `ensure_secret.yaml`'s Vault-backed branch calls `ensure_vault_secret` once per secret in a loop; every `manual`, `store: openbao` secret is read by looped tasks in `ensure_secret.yaml`, with no `include_tasks` that runs once per secret; a test asserts every task in the `secrets` role calling the module sets `no_log: true`; `process_vault_secrets.yaml` is deleted; every existing `secrets` Molecule scenario passes unchanged |
| 4 | Diff real output against the previous implementation | Not started | Every `store: openbao`, generated secret in `secret_catalog.yaml` resolves to the same value it held before the cutover, checked against a snapshot taken before stage 3 merges |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] `process_vault_secrets.yaml` no longer exists.
- [ ] No secret value appears in plaintext under `-vvv`, confirmed by a
      test that runs the module in a `no_log: true` task and asserts the
      output lacks the value, not by manual inspection.
- [ ] The `secrets` role's output does not grow per secret: a steady-state
      run prints no per-secret TASK banner or `included:` line.
- [ ] The `vault_backed` scenario's create-race case passes.
- [ ] No generated secret's value changed as a result of the cutover.

## Risks

- Stage 4's diff is destructive to run twice (each run may generate
  missing values); take the snapshot once, immediately before stage 3
  merges, not on demand.
- `tools/openbao_utils/client.py` and the new module now implement the
  same `hvac` calls twice, by design (ADR 0067's Non-goals). A future
  change to OpenBao's KV v2 behavior needs updating in both places.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or named by a successor project.
- [ ] The linked revision is `accepted`, another project still names it, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
- [ ] No code comment, message or topic doc still names this project's stages, phases or tracks.
