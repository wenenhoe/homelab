---
id: ADR-0067
revision: 0
type: adr
title: "Where the code that generates and stores a Vault-backed secret lives"
short: Vault-backed secret module
solution: "A custom Ansible module under ansible/module_utils/ + a role's library/, calling hvac directly, replacing the task-based read/generate/write/reread sequence"
summary: "Where the logic that generates, reads and CAS-writes a Vault-backed secret lives, replacing five correlated uri tasks with one module."
topic: secrets-store
status: working
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
    hidden. `AnsibleModule.no_log_values.add(value)` does redact it,
    confirmed live (`VALUE_SPECIFIED_IN_NO_LOG_PARAMETER`). The current
    `uri`-based tasks get this for free from `no_log: true` at the task
    level, which masks the whole result; a module's return path does not
    inherit that automatically.
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
- The module calls `hvac` directly. It does not import
  `tools/openbao_utils/client.py`; the spike showed that reuse needs an
  unsupported mechanism. `tools/openbao_utils/client.py` is unchanged and
  keeps serving its own callers.
- The module catches `hvac.exceptions.InvalidRequest` on the `cas=0`
  write specifically, not a generic exception, and re-reads on that path
  only. Any other exception fails the task.
- Every value the module places in its return dict is registered with
  `module.no_log_values.add(...)` before `exit_json`. The calling task
  keeps `no_log: true` as well, matching the current pattern, rather than
  relying on either alone.
- `secrets/tasks/process_vault_secrets.yaml`'s five-stage, index-correlated
  sequence is replaced by one loop over `ensure_vault_secret`, one call per
  secret. The manual/`controller_file` branch in `ensure_secret.yaml` is
  unchanged; this covers only `store: openbao` secrets with a `hex` or
  `uuid4` source, which is what `process_vault_secrets.yaml` generates —
  a `manual` secret stored in OpenBao is read, never generated, so it
  stays on the existing single-read path.
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
behavioral equivalence on the real catalog, which is Stage 2 of the
implementing project, not a design assumption.

## Consequences

- `ansible/module_utils/` and a `library/` become new top-level
  directories, alongside `filter_plugins/`; `ansible.cfg` gains a
  `module_utils` line.
- `secrets`'s existing `vault_backed` Molecule scenario, which already runs
  against a real OpenBao test target, needs a create-race case added so
  the module's `InvalidRequest`-catching branch is exercised the same way
  `process_vault_secrets.yaml`'s reread-on-conflict branch is today.
- `docs/topics/secrets/secrets.md` and `docs/topics/engineering/molecule-testing.md` describe the new module
  and its test target once implemented.

## Invariants

- A `cas=0` write conflict is handled by catching
  `hvac.exceptions.InvalidRequest`, never by a status-code check on an
  `hvac` call.
- Every value a module returns is added to `no_log_values` before
  `exit_json`, in addition to task-level `no_log: true`.
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
create-race and reuse paths; a module-level test confirms
`no_log_values` contains every value the module could return.
