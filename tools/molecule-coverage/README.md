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

Not yet implemented: static task inventory, aggregation, reporting, and
wiring into any role's `molecule.yml`.

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
