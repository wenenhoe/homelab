---
id: ADR-0067
revision: 0
type: adr
title: "Where the code that generates and stores a Vault-backed secret lives"
short: Vault-backed secret module
solution: "A custom Ansible module under ansible/module_utils/ + a role's library/, calling hvac directly, replacing the task-based read/generate/write/reread sequence"
summary: "Where the logic that generates, reads and CAS-writes a Vault-backed secret lives, replacing five correlated uri tasks with one module."
topic: secrets-store
status: approved
related: [ADR-0021, ADR-0030, ADR-0031, ADR-0066]
---

# 0067. Where the code that generates and stores a Vault-backed secret lives

## Problem

Generating a secret's value (when none exists yet), storing it in OpenBao
without racing a concurrent controller run, and reading back whichever
value won, is one operation with several branches. It has to be
expressed once, be testable without a live playbook run, and behave
identically for every secret regardless of which role needs it.

## Context

- `secrets/tasks/process_vault_secrets.yaml` does this today as five
  sequential `uri` tasks (read, generate, write with `cas=0`, re-read on
  conflict, store), each looping over its own filtered subset of the
  batch and correlating results by re-indexing `.results` into a dict
  keyed by secret name, because each stage's list has a different length
  and order than the one before it.
- `tools/openbao_utils/client.py` already wraps the same read and login
  operations with `hvac`, per
  [ADR 0030 (OpenBao Python client)](../0030-openbao-client-implementation-in-repo-python/revision-000.md).
  It is a `uv`-managed script under `tools/`, per
  [ADR 0031 (Repo tooling location)](../0031-where-repo-tooling-lives/revision-000.md), imported
  as `tools.openbao_utils.client` by other scripts in that tree.
- **Spike, confirmed live** against a real OpenBao v2.7.0 dev server and
  `ansible-core` 2.21.4:
  - A custom module cannot import `tools.openbao_utils.client` the way
    other `tools/` scripts do. Ansible's supported extension point for
    shared module code in a non-collection repo is a sibling
    `module_utils/` directory, named in `ansible.cfg`
    (`module_utils = <path>`), which a module then imports as
    `ansible.module_utils.<name>`. This repo already uses the equivalent
    convention for filters: `ansible.cfg` sets `filter_plugins =
    filter_plugins`, and that directory now holds `app_deploy_plan.py`
    and `cron_period_hours.py`.
  - Reaching `tools/openbao_utils/client.py` directly is possible only by
    relying on `PYTHONPATH` set in the shell that launches
    `ansible-playbook`, which is not how any current entry point
    (`deploy.yaml`'s invocation, CI, a cron-triggered run) launches it and
    is not a documented Ansible mechanism.
  - No interpreter mismatch exists: `ansible-core` and `hvac` are both
    declared in the same `pyproject.toml`, `uv`-managed. Ansible already
    runs inside the interpreter that has `hvac`, for every task including
    `delegate_to: localhost`.
  - `hvac` does not surface a CAS conflict as a status code the way the
    raw `uri` task's `status_code: [200, 400]` does. `create_or_update_secret(...,
    cas=0)` against a path someone else just created raises
    `hvac.exceptions.InvalidRequest` with the message "check-and-set
    parameter did not match the current version" — confirmed live by
    reproducing the exact race. A module must catch that exception, not a
    status code, to take the re-read branch.
  - `no_log: true` on a module's argument only masks inputs. A value
    placed in the module's own return dict is not masked by that alone —
    confirmed live: a generated secret returned as a plain field leaked in
    full under `-vvv` even with the module's token argument correctly
    hidden. `AnsibleModule.no_log_values.add(value)` does redact it, but
    in the result the controller receives: the playbook's registered
    variable then holds `VALUE_SPECIFIED_IN_NO_LOG_PARAMETER` instead of
    the secret, so a module cannot both return a value and have it
    redacted.
  - A module cannot censor its own result any other way. A
    `_ansible_no_log` key in the result is removed with a warning ("Removed
    reserved key '_ansible_no_log' from module result") and censors
    nothing. `no_log: true` on the calling task is the one mechanism that
    hides the whole result at every verbosity, `-vvv` and every loop item
    included, while the registered variable keeps the real value — which
    is what the current `uri`-based tasks rely on. Confirmed live against
    `ansible-core` 2.21.5 with a looped call.
- Most `store: openbao` entries in `secret_catalog.yaml` are `manual`,
  read and never generated, so they need the read `process_vault_secrets.yaml`
  gives them today. `read_vault_kv.yaml` serves one secret per include
  (`secrets_item_name`). `ansible.cfg` sets `display_ok_hosts = no` and
  `display_skipped_hosts = no`, which hide ok and skipped results but not
  the TASK banner and `included:` line each `include_tasks` prints. With
  the catalog's real proportions, routing the manual reads through a
  per-secret include printed about eight times today's lines on a
  steady-state run (44 TASK banners and 83 `included:` lines against 5 and
  5), the cost looped tasks in `ensure_secret.yaml` avoid. Confirmed live
  against `ansible-core` 2.21.5.
- [ADR 0066 (Secret definitions)](../0066-how-a-secret-definition-states-production-and-storage/revision-000.md)
  gives every entry an explicit `source`, `store` and `scope`, which is
  what a module's input shape needs and did not have before that ADR.

## Decision

- A module `ensure_vault_secret` takes one secret's `source` (`hex` |
  `uuid4`), `length` (for `hex`), `scope` and `name`, plus the Vault
  connection facts `vault_login.yaml` already publishes
  (`secrets_vault_base_url`, `secrets_vault_token`,
  `secrets_vault_ca_path`), and returns its resolved value and whether it
  generated or reused it.
- Shared read/write logic lives in `ansible/module_utils/openbao_kv.py`,
  named in `ansible.cfg`'s `module_utils` setting, mirroring the existing
  `filter_plugins` convention. The module imports it as
  `ansible.module_utils.openbao_kv`.
- The module lives in the `secrets` role's `library/`, the only role that
  calls it; Ansible finds a role's `library/` without a setting.
- The module calls `hvac` directly. It does not import
  `tools/openbao_utils/client.py`; the spike showed that reuse needs an
  unsupported mechanism. `tools/openbao_utils/client.py` is unchanged and
  keeps serving its own callers.
- The module catches `hvac.exceptions.InvalidRequest` on the `cas=0`
  write specifically, not a generic exception, and re-reads on that path
  only. Any other exception fails the task.
- The module returns the resolved value as a plain field and does not add
  it to `no_log_values`, which would hand the playbook the redaction
  marker in place of the secret. Every task that calls the module sets
  `no_log: true`, which is what keeps the value out of `-v` and `-vvv`
  output, matching the current pattern. The module's `vault_token`
  argument is `no_log=True`.
- `secrets/tasks/process_vault_secrets.yaml`'s five-stage, index-correlated
  sequence is replaced by one loop over `ensure_vault_secret`, one call per
  secret. The manual/`controller_file` branch in `ensure_secret.yaml` is
  unchanged. The module covers only `store: openbao` secrets with a `hex`
  or `uuid4` source, which is what `process_vault_secrets.yaml` generates.
- A `manual` secret stored in OpenBao is read, never generated.
  `ensure_secret.yaml` reads every one in the call with looped tasks (one
  read, one missing-secret check and one store, each a single task over
  the call's list), the shape its `controller_file` branch already has. It
  does not include a task file per secret.
- `supports_check_mode=False`, matching today's behavior: nothing here is
  meaningfully previewable, since generation only happens when a read
  finds nothing.

## Alternatives considered

- **Reuse `tools/openbao_utils/client.py` via `PYTHONPATH`.** Confirmed
  live that it can work, but only by depending on an environment variable
  set outside Ansible's own configuration, in every place the playbook is
  ever launched from. Rejected on that fragility alone.
- **Keep the task-based sequence, only fix the racy correlation.** Still
  five separately-typed tasks whose stages have to agree with each other
  by convention, and doesn't reduce the 307 lines to anything smaller.
- **A lookup plugin instead of a module.** A lookup returns a value; it
  isn't the natural place to also decide whether to generate and write
  one. The existing `zone.db.j2` use of `lookup('ansible.builtin.template', ...)`
  in `bind9` is read-only, a different shape.

## Assumptions

None remaining that the spike could resolve. What is left to prove is
behavioral equivalence on the real catalog, which the implementing
project checks against a snapshot taken before the cutover, not a design
assumption.

## Consequences

- `ansible/module_utils/` becomes a new top-level directory, alongside
  `filter_plugins/`, and `ansible.cfg` gains a `module_utils` line. The
  module sits in `ansible/roles/secrets/library/`.
- `secrets`'s existing `vault_backed` Molecule scenario, which already runs
  against a real OpenBao test target, needs a create-race case added so
  the module's `InvalidRequest`-catching branch is exercised the same way
  `process_vault_secrets.yaml`'s reread-on-conflict branch is today.
- `docs/topics/secrets/secrets.md` and `docs/topics/engineering/molecule-testing.md` describe the new module
  and its test target once implemented.
- A caller that omits `no_log: true` leaks every value the module returns,
  because the module cannot censor its own result. The tests under
  Validation are what catch that.

## Invariants

- A `cas=0` write conflict is handled by catching
  `hvac.exceptions.InvalidRequest`, never by a status-code check on an
  `hvac` call.
- Every task that calls `ensure_vault_secret` sets `no_log: true`, and the
  module never adds a value it returns to `no_log_values`.
- `tools/openbao_utils/client.py` and `ansible/module_utils/openbao_kv.py`
  stay two independent implementations of the same `hvac` calls; a future
  change to one does not imply the other must change.

## Non-goals

- Changing the manual/`controller_file` secret path.
- Changing `vault_login.yaml`'s AppRole login mechanism.
- Consolidating `tools/openbao_utils/client.py` and
  `ansible/module_utils/openbao_kv.py` into one implementation. Revisiting
  that is a later decision if the duplication proves costly.

## Validation

A Molecule scenario against a real OpenBao test target exercises the
create-race and reuse paths. A test runs the real call under `-vvv` in a
task with `no_log: true` and asserts that neither a generated nor a reused
value appears in the output, and that the registered value is the real
one. A second test asserts that every task in the `secrets` role calling
the module sets `no_log: true`.
