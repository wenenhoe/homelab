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
- **Stage 5**: wired into `caddy`'s `molecule/default/molecule.yml` as a
  proof of concept - the callback plugin is enabled during that scenario's
  converge/idempotence/verify runs automatically, no manual env vars needed
  for that one role/scenario.
- **Stage 6**: fixed the append/reset issue noted in stage 1 -
  `molecule_helpers/tasks/reset_coverage_data.yaml`, included as the first
  task in `molecule_helpers/playbooks/prepare_dind.yml` (the shared prepare
  playbook 9 of the 11 scenarios use) plus `bind9`'s own separate
  `prepare.yml` and a new one for `apt`, deletes a scenario's own JSONL
  before each `molecule test` invocation, so runs no longer accumulate
  stale data from previous ones.
- **Stage 7**: rolled the coverage env vars out to every other
  role/scenario in the repo (`apt`, `bind9`, `caddy`, `compose` x5,
  `compose_app` x2, `docker` - 11 scenarios total). `apt` had no `prepare`
  step at all, so one was added, wired to just the reset task.
- **Stage 8**: fixed a false-negative in `inventory.py` -
  `import_tasks`/`import_role`/`meta` statements never fire their own
  runtime event (verified empirically), so they're now excluded from the
  inventory entirely instead of showing as permanent, unfixable
  `never_observed` results regardless of actual coverage.

Not yet done: branch/path coverage (which side of a `when:` actually
fired) - the original motivating question, deferred until task coverage was
solid across the whole repo.

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

- `include_tasks`/`include_role` are recorded as tasks themselves but
  *not followed*. Every `*.yaml`/`*.yml` under `tasks/` is scanned
  directly regardless of whether anything includes it, so `include_tasks`
  *targets* are still counted (as long as they live under this role's own
  `tasks/` dir) — but `include_role` targets, which point at a *different*
  role, are correctly left for that role's own inventory to count,
  avoiding double-counting.
- `import_tasks`/`import_role`/`meta` statements themselves are excluded
  entirely (not just un-followed) - see Stage 8 below for why.
- A task file with no in-repo references would still show up as "should be
  covered" — dead code isn't distinguished from live code at this stage.

## Stage 8: fixing a real-world false negative (import_tasks/meta)

First live run across the whole repo (`molecule test --all` per role, then
`report.py`) surfaced `compose`'s own `tasks/main.yaml` as 100%
`never_observed` across all 5 scenarios, and one unexplained
`never_observed` task in `bind9` beyond its own `import_tasks` line.
Investigated rather than assumed a real gap, and confirmed empirically
(small throwaway roles, not docs) that this was the tool being wrong, not
the tests being incomplete:

- `import_tasks`/`import_role` are expanded at **parse time**: their
  content is spliced directly into the surrounding task list before
  execution starts, so the statement itself has no corresponding runtime
  node - Ansible never fires a `runner_on_ok`/`skipped`/`failed` event for
  it. (`include_tasks`/`include_role` are dynamic/runtime and correctly
  DO fire their own event, verified the same way - no change needed
  there.)
- `ansible.builtin.meta` (e.g. `flush_handlers`) is handled directly by
  Ansible's strategy plugin, never dispatched through the normal task
  executor the callback plugin's hooks are attached to - so it produces
  no event either, confirmed with a throwaway role exercising
  `flush_handlers` after a notified handler.

Both are now excluded from `inventory.py`'s output entirely
(`_STRUCTURALLY_UNMEASURABLE_ACTIONS`), rather than counted against
coverage - they were permanent, unfixable false negatives regardless of
how well-tested the underlying content actually was (which, for both
`compose` and `bind9`, it already was - correctly attributed to the
imported file's own tasks, just never rolled up to the `import_tasks`
line that pulled them in).

**Effect**: `compose` goes from 43/45 (95.6%) to 43/43 (100%) - its only
two gaps were this artifact. `bind9` goes from 17/20 (85%) to 17/18
(94.4%) - one of its two `never_observed` entries was real, the other
wasn't; the real one (a `skipped_only` task, separate from this fix)
still needs a look. `apt`'s 75% is untouched - no `import_tasks`/`meta`
involved there, so that gap is real and worth investigating on its own.

If you regenerate `_inventory.json` for any role after this fix, the
task counts in `report.py`'s output will shift down slightly wherever
`import_tasks`/`import_role`/`meta` were used - that's expected and
correct, not a regression.

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

## Stage 5: PoC wiring (caddy role)

`ansible/roles/caddy/molecule/default/molecule.yml`'s `provisioner.env` now
sets `ANSIBLE_CALLBACKS_ENABLED`, `ANSIBLE_CALLBACK_PLUGINS`, and
`MOLECULE_COVERAGE_DIR` (see the comment in that file for the path
reasoning). This means running that scenario normally now also produces
coverage data, with no extra env vars needed:

```bash
cd ansible
molecule test -s default -- caddy   # or however you normally invoke it
```

This should populate `tools/molecule-coverage/.data/caddy/default.jsonl`.
Combined with the static inventory (regenerate it locally - see Stage 2 -
since it contains absolute paths tied to your own checkout):

```bash
python3 ../tools/molecule-coverage/inventory.py roles/caddy \
  --coverage-dir ../tools/molecule-coverage/.data
python3 ../tools/molecule-coverage/report.py \
  --coverage-dir ../tools/molecule-coverage/.data --role caddy
```

**Known limitation carried over from stage 1, fixed in stage 6**: the
JSONL file used to accumulate across separate `molecule test` invocations.
The shared `molecule_helpers/playbooks/prepare_dind.yml` that `caddy`'s
scenario already uses for its `prepare` step now deletes it at the start
of every test run - see the Stage 6 section below.

Only `caddy`'s `default` scenario is wired up so far - this is a
proof-of-concept for one role/scenario, not a repo-wide rollout.

## Stage 6: fixing the append/reset issue

`molecule_helpers/tasks/reset_coverage_data.yaml` deletes
`$MOLECULE_COVERAGE_DIR/<role>/<scenario>.jsonl` (role/scenario taken from
Molecule's own `MOLECULE_PROJECT_DIRECTORY`/`MOLECULE_SCENARIO_NAME`, so no
hardcoded names), `delegate_to: localhost`, guarded so it's a no-op if
`MOLECULE_COVERAGE_DIR` isn't set - safe to include anywhere, whether or
not that scenario has coverage wired up yet.

This repo already has a shared prepare playbook,
`molecule_helpers/playbooks/prepare_dind.yml`, referenced directly from
`provisioner.playbooks.prepare` by 9 of the 11 scenarios (`caddy`,
`compose` x5, `compose_app` x2, `docker`) - so adding the reset task as its
first task wires up all 9 in one edit. The remaining two scenarios have
their own separate prepare playbooks (`bind9`, which manages Docker's
storage driver differently to avoid fighting over `daemon.json` with its
own DNS config - see the comment in its `prepare.yml`; and `apt`, which
previously had no `prepare` step at all since it needs no Docker-in-Docker
setup) - each got the same task added as their first task, or as their
only task in `apt`'s new `prepare.yml`.

Runs once per `molecule test` invocation (prepare runs once, before
converge/idempotence/verify), so all three of those phases still correctly
accumulate into the same fresh file for that one run - only a genuinely
new invocation gets a clean slate.

## Stage 7: rolled out to every role

Every scenario in the repo now has the same three `provisioner.env` vars
as `caddy`. Since `MOLECULE_PROJECT_DIRECTORY` is always a role's own
directory (`ansible/roles/<role>`) regardless of which scenario within it
is running, the same `${MOLECULE_PROJECT_DIRECTORY}/../../../tools/...`
path works unchanged across every role and scenario.

Once you've run `molecule test` for a scenario, generate its inventory and
view the report the same way as the caddy PoC:

```bash
cd ansible
python3 ../tools/molecule-coverage/inventory.py roles/<role> \
  --coverage-dir ../tools/molecule-coverage/.data

python3 ../tools/molecule-coverage/report.py \
  --coverage-dir ../tools/molecule-coverage/.data
# or, for one role's per-task detail:
python3 ../tools/molecule-coverage/report.py \
  --coverage-dir ../tools/molecule-coverage/.data --role <role>
```

The summary table naturally aggregates across every role you've generated
an inventory + run scenarios for - it doesn't require running every
role/scenario at once.
