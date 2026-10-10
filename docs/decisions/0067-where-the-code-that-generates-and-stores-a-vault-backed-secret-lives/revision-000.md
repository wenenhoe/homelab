---
id: ADR-0067
revision: 0
type: adr
title: "Where the code that generates and stores a Vault-backed secret lives"
short: Vault-backed secret module
solution: "A custom Ansible module under ansible/module_utils/ + a role's library/, calling hvac directly, replacing the task-based read/generate/write/reread sequence"
summary: "Where the logic that generates, reads and CAS-writes a Vault-backed secret lives, replacing five correlated uri tasks with one module."
topic: secrets-store
status: accepted
related: [ADR-0021, ADR-0030, ADR-0031, ADR-0066]
---

# 0067. Where the code that generates and stores a Vault-backed secret lives

## Problem

Generating a secret's value when none exists, storing it in OpenBao without racing a concurrent controller run, and reading back whichever value won is one operation with several branches. It has to be expressed once, be testable without a live playbook run, and behave the same for every secret and every role.

## Context

- When this was decided, `secrets/tasks/process_vault_secrets.yaml` (removed) did it as five sequential `uri` tasks (read, generate, write with `cas=0`, re-read on conflict, store). Each looped over its own filtered subset of the batch, and results were correlated by re-indexing `.results` into a dict keyed by secret name.
- `tools/openbao_utils/client.py` wraps the same operations with `hvac` ([ADR 0030 (OpenBao Python client)](../0030-openbao-client-implementation-in-repo-python/revision-000.md)) as a `uv`-managed script under `tools/` ([ADR 0031 (Repo tooling location)](../0031-where-repo-tooling-lives/revision-000.md)). A module cannot import it the way other `tools/` scripts do. Ansible's supported home for shared module code in a repo without a collection is a `module_utils/` directory named in `ansible.cfg`, imported as `ansible.module_utils.<name>`; `filter_plugins` already follows the same convention. Reaching `client.py` instead depends on a `PYTHONPATH` that no entry point sets and Ansible does not document. `ansible-core` and `hvac` come from one `pyproject.toml`, so a module runs in the interpreter that has `hvac`.
- `hvac` reports a `cas=0` conflict as `hvac.exceptions.InvalidRequest` ("check-and-set parameter did not match the current version"), not as a status code the way `uri`'s `status_code: [200, 400]` does.
- A module cannot hide a value it returns. `no_log: true` on an argument masks inputs only, and a returned value printed in full under `-vvv`. `no_log_values.add(value)` redacts it in the result the controller receives, so the playbook's registered variable holds `VALUE_SPECIFIED_IN_NO_LOG_PARAMETER`. A `_ansible_no_log` key is stripped with a warning. Only `no_log: true` on the calling task hides the whole result at every verbosity, loop items included, while the registered variable keeps the real value. Confirmed against `ansible-core` 2.21.5.
- Most `store: openbao` entries are `manual`: read, never generated. `ansible.cfg` sets `display_ok_hosts = no` and `display_skipped_hosts = no`, which hide ok and skipped results but not the TASK banner and `included:` line of each `include_tasks`. At the catalog's proportions, reading manual secrets through a per-secret include printed about eight times as many lines on a steady-state run (44 banners and 83 `included:` lines against 5 and 5). Looped tasks avoid that cost.
- [ADR 0066 (Secret definitions)](../0066-how-a-secret-definition-states-production-and-storage/revision-000.md) gives every entry an explicit `source`, `store` and `scope`, which is the module's input shape.

## Decision

- A module `ensure_vault_secret` takes one secret's `name`, `source` (`hex` | `uuid4`), `length` (for `hex`) and `scope`, plus the connection facts `vault_login.yaml` publishes, and returns its value and whether it generated or reused it. It supports no check mode: generation happens only when a read finds nothing, so there is nothing to preview.
- It lives in the `secrets` role's `library/`, the only role that calls it; Ansible finds a role's `library/` without a setting. Its shared read and write logic lives in `ansible/module_utils/openbao_kv.py`, named in `ansible.cfg`'s `module_utils` setting.
- The module calls `hvac` directly and does not import `tools/openbao_utils/client.py`. It catches `hvac.exceptions.InvalidRequest` on the `cas=0` write, and only there, and re-reads on that path. Any other exception fails the task.
- The module returns the value as a plain field and does not add it to `no_log_values`. Every task that calls it sets `no_log: true`. Its `vault_token` argument is `no_log=True`.
- `process_vault_secrets.yaml` is replaced by one loop over `ensure_vault_secret` in `ensure_secret.yaml`, one call per `hex` or `uuid4` secret stored in OpenBao. The manual/`controller_file` branch is unchanged.
- A `manual` secret stored in OpenBao is read, never generated. `ensure_secret.yaml` reads all of them in a call with looped tasks (one read, one missing-secret check, one store), the shape its `controller_file` branch has, and includes no task file per secret.

## Alternatives considered

- **Reuse `tools/openbao_utils/client.py` via `PYTHONPATH`.** It works, but only through an environment variable set outside Ansible's configuration wherever the playbook is launched.
- **Keep the task sequence and fix the correlation.** Still five separately typed tasks that agree by convention.
- **A lookup plugin.** A lookup returns a value; deciding whether to generate and write one is not its shape.

## Consequences

- `ansible/module_utils/` is a new top-level directory beside `filter_plugins/`, and `ansible.cfg` gains a `module_utils` line.
- A caller that omits `no_log: true` leaks every value the module returns, since the module cannot censor its own result. The tests under Validation catch that.

## Invariants

- A `cas=0` conflict is handled by catching `hvac.exceptions.InvalidRequest`, never by a status-code check.
- Every task that calls `ensure_vault_secret` sets `no_log: true`, and the module never adds a returned value to `no_log_values`.
- `tools/openbao_utils/client.py` and `ansible/module_utils/openbao_kv.py` stay two independent implementations of the same `hvac` calls; a change to one does not imply the other must change.

## Non-goals

- Changing the manual/`controller_file` path or `vault_login.yaml`'s AppRole login.
- Merging `client.py` and `openbao_kv.py`. Revisit if the duplication proves costly.

## Validation

A Molecule scenario against a real OpenBao test target covers the create-race and reuse paths. A test runs the real call under `-vvv` in a task with `no_log: true` and asserts that neither a generated nor a reused value appears in the output and that the registered value is the real one. Another asserts that every task in the `secrets` role that calls the module sets `no_log: true`.
