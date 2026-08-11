# molecule-coverage

Task, loop, and branch coverage reporting for Ansible roles tested with
Molecule.

Molecule's `verify.yml` checks *behaviour* - did the role converge to the
right end state. It doesn't check *test coverage* - did every task, every
loop item, and every side of every `when:` actually get exercised by at
least one scenario. This tool answers that second question, using signal
Ansible already reports for free (task results, skip reasons, per-item
loop results) via a callback plugin - no changes to your roles or
`verify.yml` needed.

## What it measures

- **Task coverage** - did every task in a role's `tasks/` directory
  actually run, across all of a role's scenarios combined.
- **Loop-item granularity** - for looped tasks, whether *individual
  items* ran or only ever got skipped, even when the task overall reports
  "covered" (Ansible marks a loop as ok/changed if *any* item succeeded,
  which can hide the rest never running).
- **Branch coverage** - for tasks with a `when:`, whether you've ever
  confirmed *both* what happens when it's true and what happens when it's
  false. "Covered" alone doesn't tell you the skip path was ever tested.

Not measured: which specific clause of a compound `when: [a, b]` caused a
skip (Ansible's callbacks only expose the final combined result, never
individual clause values - see `DEVLOG.md` for why this was ruled out
rather than attempted).

## Quick start

```bash
# 1. Run your scenario(s) normally - the callback plugin + reset task are
#    already wired into every scenario's molecule.yml/prepare step in
#    this repo, so no extra flags are needed.
cd ansible
molecule test -s default   # or --all for one role, or ./molecule-test-all.sh for every role

# 2. Generate (or refresh) the static task inventory for a role
python3 molecule-coverage/inventory.py roles/caddy \
  --coverage-dir molecule-coverage/.data

# 3. View the report
python3 molecule-coverage/report.py \
  --coverage-dir molecule-coverage/.data --role caddy
```

`inventory.py` only needs re-running when a role's tasks change (or after
moving/re-cloning the repo - its output contains absolute paths tied to
your checkout, which is why it's gitignored). `report.py` reads whatever
inventory + execution data already exists in the coverage dir.

To regenerate the inventory for every role with a `molecule/` folder (or
one role by name) in one go, instead of re-running step 2 by hand for
each - see [`inventory-all.sh`](inventory-all.sh):

```bash
cd ansible
./molecule-coverage/inventory-all.sh            # every role
./molecule-coverage/inventory-all.sh caddy       # just one
```

## Usage

```bash
# Summary table across every role with data under the coverage dir
python3 report.py --coverage-dir molecule-coverage/.data

# Per-task drill-down for one role - sorted in source order (file
# alphabetically, then line in sequence), so it reads like the code
python3 report.py --coverage-dir molecule-coverage/.data --role caddy

# Summary, then every role's drill-down, in one go
python3 report.py --coverage-dir molecule-coverage/.data --show-all

# Exit 1 if any role's coverage is below a threshold - pr-checks.yml's
# molecule job uses --thresholds-file instead, for per-role floors
python3 report.py --coverage-dir molecule-coverage/.data --fail-under 80
python3 report.py --coverage-dir molecule-coverage/.data --role caddy \
  --thresholds-file molecule-coverage/thresholds.yaml
```

A drill-down row looks like this:

```
Status   Task                       Location      Loop          Branch          Per-scenario
covered  Restart the service        tasks.yaml:42  -             never negated   default=covered
covered  Copy config files          tasks.yaml:50  2 item(s) ok  -               default=covered
```

- **Status**: `covered` / `skipped_only` / `never_observed`, unioned
  across all scenarios for that role.
- **Loop**: `-` if the task has no loop; otherwise how many distinct
  items ran vs. only ever got skipped, or `empty loop` if it was only
  ever seen with zero items.
- **Branch**: `-` if the task has no `when:`; otherwise `both ok`,
  `never negated` (only ever true - the skip path is untested), or
  `never satisfied` (only ever false).
- Problem tasks (partial loop gaps, never-negated conditions) are called
  out again explicitly in a summary note below the table, regardless of
  where they land in the source-ordered list.

## How it's wired in

The three env vars this needs (`ANSIBLE_CALLBACKS_ENABLED=molecule_coverage`,
`ANSIBLE_CALLBACK_PLUGINS`, `MOLECULE_COVERAGE_DIR`) live in
`.config/molecule/config.yml` at the repo root - Molecule's "base config",
auto-discovered and deep-merged into every scenario's own `molecule.yml`,
rather than repeated in each of the 11 scenario files individually (they
were byte-for-byte identical across all of them before this). Adding a
new scenario inherits these automatically - nothing to add there beyond
the scenario's own `molecule.yml`. A reset task
(`molecule_helpers/tasks/reset_coverage_data.yaml`) runs first in every
scenario's prepare step so each `molecule test` invocation starts from a
clean slate instead of accumulating stale data from previous runs.
Nothing needs to change to start collecting coverage for a scenario that
already exists in this repo - it's automatic.

## Known limitations

- **`include_role` targets aren't followed.** A role that dispatches most
  of its real work into another role (e.g. `caddy` → `compose`) is scored
  only on its own `tasks/` directory; the other role's own coverage is
  reported separately, under its own name.
- **Dead code isn't detected.** Every file under `tasks/` is scanned,
  whether or not anything actually reaches it - an unreachable file would
  still show up as "should be covered."
- **No per-clause attribution for compound `when:`.** Only the whole
  condition's true/false is tracked, not which part of an `and`/`or`
  caused a skip.
- **`no_log: true` loops undercount.** Ansible redacts the item value
  from every hook when `no_log` is set, so multiple genuinely different
  items collapse into a single "ran"/"skipped" bucket rather than an
  exact per-item count.
- **`_inventory.json` is machine-local** (absolute paths) - regenerate
  after moving or re-cloning the repo, never commit it (already
  gitignored).
- **No trend history.** Each report run is a snapshot; nothing tracks
  whether coverage is improving over time beyond what's visible by
  comparing successive PRs' step summaries.
