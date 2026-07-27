# molecule-coverage

Task (and, later, branch) coverage reporting for Ansible roles tested with
Molecule. Lives in its own directory so it can eventually be pulled out into
a standalone tool/collection without disturbing the rest of this repo.

## Why

Molecule verifies *behaviour* (did the role converge to the right end state),
not *test coverage* (did every task, and every side of every `when:`, actually
get exercised by at least one scenario). Ansible-core already reports
skip-vs-executed per task per host for free; this tool just captures that
signal across all Molecule scenarios and reports on it.

## Status

Being built incrementally. See the repo's conversation history / commit log
for the staged plan. Currently implemented:

- **Stage 1**: `callback_plugins/molecule_coverage.py` — records task
  execution/skip events (per scenario, per host, per task) to JSONL files.
- **Stage 2**: `inventory.py` — statically enumerates every task defined
  under a role's `tasks/` directory (the denominator coverage % is measured
  against).
- **Stage 3**: `aggregate.py` — joins the inventory against per-scenario
  execution events to classify every task as covered / skipped-only / never
  observed, per scenario and aggregated (union) across all of a role's
  scenarios.
- **Stage 4**: `report.py` — human-readable CLI: a summary table across
  every role with data, a per-task drill-down for one role, and an optional
  `--fail-under` threshold (exit 1 if below - available, not enforced).

Not yet implemented: wiring into any role's `molecule.yml` (still a manual
env var dance today - see below).

## Stage 1 usage (manual, for now)

The callback plugin is disabled by default (`CALLBACK_NEEDS_ENABLED = True`).
To try it against any playbook run:

```bash
export ANSIBLE_CALLBACKS_ENABLED=molecule_coverage
export ANSIBLE_CALLBACK_PLUGINS=$(pwd)/../tools/molecule-coverage/callback_plugins
export MOLECULE_COVERAGE_DIR=$(pwd)/../tools/molecule-coverage/.data
export MOLECULE_COVERAGE_ROLE=myrole      # optional, see below
export MOLECULE_COVERAGE_SCENARIO=myscen  # optional, see below

ansible-playbook some_playbook.yml
```

This will produce
`tools/molecule-coverage/.data/<role>/<scenario>.jsonl`, one JSON object per
line, e.g.:

```json
{"scenario": "default", "role": "caddy", "task_name": "Deploy Caddyfile from template and host_vars", "task_file": "/path/to/caddy/tasks/main.yaml", "task_line": 14, "action": "ansible.builtin.template", "status": "ok", "host": "caddy-instance", "timestamp": "2026-07-27T12:00:00+00:00"}
```

`role`/`scenario` are taken from `MOLECULE_COVERAGE_ROLE` /
`MOLECULE_COVERAGE_SCENARIO` if set, otherwise the plugin falls back to
Molecule's own `MOLECULE_PROJECT_DIRECTORY` / `MOLECULE_SCENARIO_NAME` env
vars (set automatically inside any Molecule-managed playbook run), and
finally to `"unknown"` if neither is available — this lets the same plugin
be used standalone (like the example above) or wired into Molecule later.

Later stages will replace the manual env var dance above with a couple of
lines in each scenario's `molecule.yml`.

## Stage 2 usage

```bash
python3 tools/molecule-coverage/inventory.py ansible/roles/caddy --stdout
```

Or, to write to the same `.data/<role>/` directory the callback plugin uses
(dropping `--stdout` and optionally passing `--coverage-dir`, which
otherwise falls back to `MOLECULE_COVERAGE_DIR` / `./.molecule-coverage-data`
just like the callback plugin):

```bash
python3 tools/molecule-coverage/inventory.py ansible/roles/caddy \
  --coverage-dir tools/molecule-coverage/.data
```

This writes `tools/molecule-coverage/.data/caddy/_inventory.json` — a flat
list of every task found under `ansible/roles/caddy/tasks/`, recursing into
`block`/`rescue`/`always`, e.g.:

```json
{
  "task_name": "Deploy Caddyfile from template and host_vars",
  "task_file": "/path/to/ansible/roles/caddy/tasks/main.yaml",
  "task_line": 18,
  "action": "ansible.builtin.template"
}
```

**Known, deliberate limitations** (not goals for this stage):

- `include_tasks`/`import_tasks`/`include_role` are recorded as tasks
  themselves but *not followed*. Every `*.yaml`/`*.yml` under `tasks/` is
  scanned directly regardless of whether anything includes it, so
  include/import *targets* are still counted (as long as they live under
  this role's own `tasks/` dir) — but `include_role` targets, which point
  at a *different* role, are correctly left for that role's own inventory
  to count, avoiding double-counting.
- A task file with no in-repo references would still show up as "should be
  covered" — dead code isn't distinguished from live code at this stage.

## Stage 3 usage

Requires stage 1 (JSONL events) and stage 2 (`_inventory.json`) to already
exist for a role under the same coverage directory, e.g.
`tools/molecule-coverage/.data/caddy/` containing `_inventory.json` plus one
`<scenario>.jsonl` per scenario that's been run with the callback enabled.

```bash
python3 tools/molecule-coverage/aggregate.py tools/molecule-coverage/.data/caddy
```

Prints a JSON report to stdout: every task from the inventory, joined
against execution events by `(task_file, task_line)` (verified to match
exactly between stages 1 and 2 - not task name, which isn't guaranteed
unique and differs slightly between the two: the callback records ansible's
`role : task name` context string). Each task gets a status per scenario,
plus an aggregate status that's the union across all scenarios - so a task
only skipped in one scenario but executed in another is correctly reported
as covered overall. Three possible statuses:

- `covered` - executed (ok/changed/failed) in at least one scenario
- `skipped_only` - its `when:` was reached but never true, in every
  scenario that reached it
- `never_observed` - not present in any scenario's events at all (the
  containing task file was never even loaded)

A `summary` block gives the totals and an overall `coverage_pct` (percentage
of tasks with aggregate status `covered`).

Not yet built: a human-readable/tabular view of this (stage 4) - for now
it's raw JSON, useful for scripting but not for a quick glance.

## Stage 4 usage

```bash
# Summary table across every role with data under the coverage dir
python3 tools/molecule-coverage/report.py --coverage-dir tools/molecule-coverage/.data

# Per-task drill-down for one role, worst offenders (never_observed, then
# skipped_only) sorted first
python3 tools/molecule-coverage/report.py --coverage-dir tools/molecule-coverage/.data --role caddy

# Exit 1 if any reported role is below a coverage threshold - available
# for a future CI gate, not required or wired into anything yet
python3 tools/molecule-coverage/report.py --coverage-dir tools/molecule-coverage/.data --fail-under 80
```

`report.py` imports `aggregate.py` directly (both live in this directory),
so it can be run from any working directory - it resolves the import
relative to its own file location rather than relying on cwd.
