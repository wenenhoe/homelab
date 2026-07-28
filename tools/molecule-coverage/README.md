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
- **Stage 9**: loop-item granularity. A looped task where only one item
  ever satisfies its condition previously showed plain task-level
  "covered", hiding that the other items never ran - `report.py` now
  surfaces this directly (see the Stage 9 section below).
- **Stage 9.1**: fixed a real bug in stage 9, caught on first live run
  against `bind9` - `no_log: true` redacts a loop item's value from
  *every* hook (task-level and per-item alike), which the original
  `item is not None` check misread as "not an item event", silently
  losing per-item detail for any `no_log`'d loop. Fixed by tracking which
  hook fired explicitly (`is_item`) instead of inferring it from whether
  the item's value survived redaction - see the note in the Stage 9
  section below.
- **Stage 10**: task-level branch coverage - the original motivating
  question, scoped down to what's empirically achievable (see the Stage
  10 section below for why full per-clause attribution of a compound
  `when: [a, b]` isn't). For any task with a `when:`, tracks whether it
  was ever observed executed (true branch) *and* ever observed genuinely
  skipped (false branch) - "covered" alone doesn't tell you whether the
  skip path was ever actually exercised.
- **Stage 10.1**: fixed a real false-negative in stage 10, caught on
  first real multi-scenario run against `compose` - a looped task's
  `when:` being false can make its OWN loop source empty too (a common
  pattern: a prior when:-gated task would've populated the loop var, so
  `| default([])` silently empties it once that task is skipped) -
  and Ansible reports that as skip_reason "No items in the list", not
  "Conditional result was False", indistinguishable from a genuinely
  unrelated empty loop. The original code excluded that reason from
  counting as a false-branch observation, which silently missed real
  evidence. See the note in the Stage 10 section below.

Not yet done: full per-clause attribution for compound `when:` conditions
- deliberately out of scope, see Stage 10.

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

# Per-task drill-down for one role, sorted in source order (file
# alphabetically, then line in sequence) so it reads like the code -
# problem tasks are called out separately in the summary notes below,
# not by reordering the table
python3 tools/molecule-coverage/report.py --coverage-dir tools/molecule-coverage/.data --role caddy

# Summary, then every role's drill-down, in one go (mutually exclusive
# with --role - pick one or the other)
python3 tools/molecule-coverage/report.py --coverage-dir tools/molecule-coverage/.data --show-all

# Exit 1 if any reported role is below a coverage threshold - available
# for a future CI gate, not required or wired into anything yet
python3 tools/molecule-coverage/report.py --coverage-dir tools/molecule-coverage/.data --fail-under 80
```

`report.py` imports `aggregate.py` directly (both live in this directory),
so it can be run from any working directory - it resolves the import
relative to its own file location rather than relying on cwd.

**Drill-down sort order**: the per-task table is sorted in source order
(file alphabetically, then line number in sequence), so it reads the same
way as the actual code - not by status/problem-first, which earlier
versions did (see the Stage 9/10 sections for what that used to look
like). Problem tasks (partial loop gaps, never-negated `when:`s) are
still called out explicitly in the summary notes below the table
regardless of where they happen to sort; the `Status`/`Loop`/`Branch`
columns are visible on every row either way.

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

## Stage 9: loop-item granularity

Task-level coverage has a real blind spot for looped tasks: Ansible
reports the task overall as "ok"/"changed" if **any** item satisfies its
condition, even if others don't - so a loop where only 1 of 3 items ever
runs still shows plain `covered`, identical to a loop where all 3 ran.
Verified empirically (throwaway roles, not assumed from docs) that:

- Ansible fires a separate `v2_runner_item_on_ok`/`skipped`/`failed`
  event **per loop iteration**, in addition to the aggregate task-level
  event - so per-item detail is available for free, just wasn't being
  captured.
- An empty loop (`loop: []`) fires **neither** hook - only the aggregate
  task-level skip, with `skip_reason` `"No items in the list"`,
  distinguishable from a plain `when: false` skip
  (`"Conditional result was False"`).

Changes across all four files:

- **`callback_plugins/molecule_coverage.py`**: added
  `v2_runner_item_on_ok/skipped/failed` hooks, writing the same event
  shape as before plus two new fields: `item` (`null` for task-level
  events, the loop item's value - JSON-safe, falling back to `str()` - for
  item-level ones) and `skip_reason` (Ansible's own skip explanation,
  `null` when not applicable).
- **`inventory.py`**: each task entry now has a `has_loop` boolean,
  detected via the `loop:` key (plus the legacy `with_*` family for
  future-proofing, though only `loop:` is actually used anywhere in this
  repo - verified via grep).
- **`aggregate.py`**: for `has_loop` tasks, an additional
  `loop_coverage` block: `items_observed_count` (distinct items ever
  executed, any scenario), `items_skipped_only` (distinct items *only*
  ever skipped, capped at 10 for huge loops, with
  `items_skipped_only_count`/`items_skipped_only_truncated` alongside),
  and `observed_empty_loop` (whether any scenario saw the empty-loop skip
  reason). Unioned across scenarios the same way `aggregate_status` is -
  an item counts as observed if it ran in *any* scenario, even if skipped
  in others.
- **`report.py`**: a new `Loop` column in the per-role drill-down (`-` for
  non-looped tasks). Originally also bumped tasks with a nonzero
  `items_skipped_only_count` up the sort order despite their
  `aggregate_status` being `covered`; the table is now sorted in source
  order instead (file/line, see the later note on this), so that
  surfacing happens via the summary note below the table instead - still
  flags how many such tasks exist and lists them.

Not changed: the top-level `aggregate_status`/coverage percentage
computation - loop detail is purely additive, so existing numbers for
non-looped tasks (and the overall coverage_pct) are unaffected. Validated
against every real role in the repo (no crashes, including roles with
zero execution data yet) and against synthetic fixtures covering: a fully
covered loop, a partially-covered loop (the case this stage exists for),
an empty loop, and a plain non-looped task.

**Stage 9.1 - a real bug, caught on first live run**: `bind9`'s actual
report showed three genuinely-looped, genuinely-covered tasks
(`Render candidate zone file content in-memory`,
`Read back whatever zone file is currently live, if any`,
`Write zone file when its non-serial content has changed`) all showing
`Loop: no items observed` - a combination that should be impossible (if
covered, *something* executed). Root cause, confirmed empirically: all
three have `no_log: true`, which redacts the *entire* result dict Ansible
hands to the callback - not just the log output, but the `item` key
itself - for both the per-item hooks AND the task-level aggregate. The
original code used `item is not None` to tell item-level events apart
from task-level ones; under `no_log`, every event's `item` comes back
`None` regardless of which hook fired, so every `no_log`'d loop iteration
was silently misfiled as a non-item event, and `loop_coverage` ended up
empty even though the loop genuinely ran.

Fixed by adding an explicit `is_item` field to the event schema, set by
the callback based on *which hook fired* (`v2_runner_item_on_*` vs.
`v2_runner_on_*`), never inferred from whether the item's value survived
redaction. When `is_item` is true but the item value was redacted, it's
stored as the literal string `"<redacted by no_log>"` rather than left
ambiguous as `null`. `aggregate.py`'s `_loop_events_by_key` and
`_empty_loop_observed_by_key` both switched from checking `item is None`
to checking `is_item`.

**Known residual limitation, not fixable without changing what `no_log`
means**: since `no_log` redacts every item's *value*, multiple genuinely
different items in the same `no_log`'d loop collapse into a single
`"<redacted by no_log>"` bucket - so `items_observed_count` for such a
loop will under-count (e.g. `bind9`'s 1-zone-plus test fixture correctly
shows activity now, but a loop with 3 real `no_log`'d items that all ran
would still only show `1`, not `3`). This is an inherent tradeoff of
`no_log`'s own redaction, not something this tool can recover - the
practically important fix is telling "ran" apart from "never observed",
which is what's fixed here; exact per-item counts under `no_log` remain
unavailable by design.

## Stage 10: task-level branch coverage

The original motivating question for this whole project was "which side
of a `when:` actually fired" - this stage answers a scoped-down version
of it, honestly:

**What's built**: for any task with a `when:` (single string, or a list
of clauses ANDed together - both normalized to a list in `inventory.py`'s
new `"when"` field), whether it was ever observed **executed** (true
branch) and ever observed **genuinely skipped** (false branch) across ALL
raw events for that task, unioned across every scenario. `aggregate.py`
adds a `branch_coverage` block (`true_branch_observed`,
`false_branch_observed`, `branch_status`:
`both_branches`/`true_only`/`false_only`/`never_observed`); `report.py`
adds a `Branch` column and lists the exact `when:` clause(s) for any
`true_only` ("never negated") task in a summary note below the table
(originally also bumped such tasks up the sort order the same way
partial-loop-gap tasks were; the table is now sorted in source order
instead - see the later note on this - so the note below is what
surfaces it).

A task that executes every single time it's reached, in every scenario,
might have a `when:` that's dead weight - nobody's ever confirmed what
the skip path even does. This is genuinely different information from
`aggregate_status`, and it comes from data already being collected -
notably, **idempotence's second `converge` pass is a natural source of
this**: a task that legitimately executes once (state not yet achieved)
and then correctly skips the second time (state already matches) already
proves both branches within a single scenario, a signal the existing
per-scenario classification discarded (it only keeps the union of
statuses per scenario, not "was a skip ALSO seen after a covered run").
Verified with a throwaway role simulating exactly that pattern (a
`stat`-gated marker file: pass 1 creates it and changes, pass 2 sees it
exists and skips) - correctly detected as `both_branches`.

**What's explicitly NOT built, and why**: attributing which specific
clause of a compound `when: [a, b]` (or `when: "a and b"`) caused a skip.
Ansible's callback hooks only ever expose the *final combined* boolean
result of the whole condition - never each clause's individual value.
Getting real attribution would mean hooking Ansible's conditional
evaluator directly (not something a callback plugin can do) or
re-implementing a meaningful chunk of Jinja2 conditional evaluation
against captured facts to reverse-engineer which clause was responsible
(fragile, and a much bigger, riskier undertaking than anything else in
this tool). The individual clauses ARE captured and shown for a
`true_only` finding (so a human reviewing "this `when:` was never
negated" can see the compound condition at a glance and reason about
which part is suspect) - but that's static context for a person to read,
not an empirical per-clause claim.

Validated: a synthetic fixture covering all four `branch_status` values
(including the idempotence-both-branches case, run for real, twice, not
simulated), and a full regression pass against every real role in the
repo with zero crashes, including the zero-execution-data case (shows
`no data` rather than erroring for `when:`-having tasks with nothing
observed yet).

**Stage 10.1 - a real false negative, caught on the first real
multi-scenario run**: `compose`'s own `report.py --show-all` output
showed `Force remove containers found via label fallback`
(`cleanup.yaml:37`) as `never negated`, despite its `Per-scenario` column
clearly showing `volumes=skipped_only` alongside `cleanup=covered` -
which should mean both branches WERE observed, across those two
scenarios. Investigated rather than assumed correct:

- That task has a task-level `when:` (not referencing `item`) AND a
  `loop:` over a var populated by an earlier task gated by that SAME
  `when:` - a natural, common pattern (seen verbatim in this repo, not a
  contrived edge case).
- Confirmed empirically (throwaway roles, not docs) that when such a
  task's `when:` is false, Ansible reports the skip's `skip_reason` as
  `"No items in the list"` - **not** `"Conditional result was False"` -
  because the loop source ends up empty as a downstream consequence.
- Also confirmed the same message appears for a genuinely-unrelated
  empty loop with `when: true` - the reason string is ambiguous in BOTH
  directions; Ansible's own data cannot distinguish "false because of
  the when:" from "empty for unrelated reasons" once a loop is involved.

The original code excluded the empty-loop reason from counting as a
false-branch observation (reasonable in isolation, matches `loop_coverage`
's own, differently-scoped use of the same reason), which caused this
real evidence to be silently dropped. Fixed by no longer excluding it for
branch-coverage purposes specifically: any `"skipped"` status now counts,
regardless of reason. This can't be made perfectly precise either way
given Ansible's own ambiguity, so the choice follows this tool's standing
principle from stages 8 and 9.1 - missing real evidence (silent false
negative) is worse than occasionally over-crediting an ambiguous case
(rarer false positive, only when a loop is independently empty AND the
task's `when:` happens to be unrelated and always true). Verified against
a two-scenario reproduction of the exact real pattern (directory-present
vs. directory-missing, matching `compose`'s `volumes`/`cleanup`
scenarios) - now correctly shows `both_branches`; re-ran the full
synthetic fixture suite from the original Stage 10 validation plus this
new case together, no regressions.
