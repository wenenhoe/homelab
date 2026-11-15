---
id: EXP-ci-timing-and-grouping
title: "How should CI keep its test groups balanced as the suites grow?"
type: exploration
status: open
summary: "Whether to record scenario and test times on a schedule and rebalance the Molecule shards from them, and whether the Python unit tests need grouping, parallelism or faster slow tests."
topic: repository-tooling
related: [ADR-0064]
---

# How should CI keep its test groups balanced as the suites grow?

The Molecule shards in `.github/molecule-shards.yml` were balanced once, on measured scenario times, and nothing re-measures them. A scenario added to a split role lands in a shard by hand, and a role that is not split can grow past the longest leg without anything saying so. The Python unit tests are one job, `python-unit-tests`, and have grown with `tools/`. Both questions are about the same thing: a run takes as long as its slowest job, and the groups that decide it are only as good as the times behind them.

## What bears on it

### Molecule

- Four roles are split (`secrets`, `step_ca_cert`, `compose`, `backup_agent`); the other 27 run as one leg each. The repo has 63 scenarios. `secrets` has 10, `step_ca_cert` and `compose` 6 each.
- [`molecule-test-all.sh`](../../ansible/scripts/molecule-test-all.sh) already times every scenario and prints the table, but only into the job summary. A job summary is not an artifact and has no API of its own, so the numbers can be read off a run's page and not collected.
- A pull request runs only the roles its diff touches ([change scoping](../topics/engineering/ci/change-scoping.md)). Times collected from pull requests alone therefore describe the roles that change often and say nothing about the rest.
- Each leg uploads its coverage data as an artifact already, so an artifact for timings follows an existing pattern.
- `renewal_timing` waits for real time (about 50 seconds) and is a shard of its own; its time does not vary with load, the others' do.
- The table is checked for coverage by `ci.scope.molecule_shards`, not for balance. Nothing fails when a shard drifts.
- A split costs about 15 seconds of checkout and setup per extra leg, and a run that queues every role is limited by the plan's concurrent-job cap, not by its longest leg ([sharded roles](../topics/engineering/ci/pipeline.md#sharded-roles)). A better table helps a run that queues few roles; it does little for a full sweep.

### Python unit tests

Measured on a two-core machine with the project's locked environment, not on a CI runner: 5,269 tests across 189 files in about 267 seconds.

| Directory | Seconds | Tests |
| :--- | ---: | ---: |
| `tools/tests/opnsense_seed` | 111 | 120 |
| `tools/tests/land_series` | 50 | 129 |
| `tools/tests/ci` | 33 | 2,041 |
| `tools/tests/doc_scripts` | 22 | 1,119 |
| `tools/tests/progress_log` | 16 | 94 |
| `ansible/tests` | 14 | 767 |
| the rest | 20 | about 1,000 |

- Time is concentrated, not spread: `test_update_gateway.py`, `test_land_landing.py` and `test_import_seed.py` are 150 of the 265 seconds, and one test in `test_import_seed.py` takes 30 seconds alone. Splitting into groups cannot take a group below its longest test.
- With `pytest-xdist` (`-n 4`, no other change) the same run took 129 seconds on the same two cores, and every test passed. Whether any test depends on running in a fixed order or on a shared path or port is not known beyond that one run.
- `python-unit-tests` is a required check under that name, directly ([requiring checks](../topics/engineering/ci/pipeline.md#requiring-checks-before-merge)). Turning it into a matrix changes the check names, which means adding it to `matrix-jobs-gate`'s `needs` and `MATRIX_JOBS` and taking the name out of the ruleset.
- Adding a dependency touches `pyproject.toml` and `uv.lock`, which stops the series replay for confirmation.

### Not known yet

- How long `python-unit-tests` takes on the runner, and whether it is ever the job a pull request waits for. If the longest Molecule leg is already longer, shortening it moves nothing.
- Whether Molecule scenario times on the runner are stable enough from run to run that one measurement is worth acting on, or whether a rolling median is needed.
- Whether the plan's minutes are free for this repository, which sets what a weekly full run costs.

## Options

### Recording molecule timings

- **Record on every pull request run.** Each leg writes its timings as a small JSON artifact next to its coverage data. No extra runs. The data is biased to the roles that change, so a rarely changed role is measured rarely, and a shard table built on it is least reliable where it is least exercised.
- **A scheduled run of every scenario.** A weekly or fortnightly workflow runs all 63 scenarios, one leg per role with the existing script, and uploads the timings. Complete and the same shape each time. It costs a full run on schedule, and a role stops at its first failing scenario, so a broken role has no timings for the scenarios after it. One leg per scenario avoids that and costs about 15 seconds of setup each.
- **Both.** The scheduled run is the baseline, pull request artifacts fill in between. More to read, and two sources of different quality to reconcile.

How often is a smaller question than which. Scenario times drift slowly and a table is only worth changing when a role gains or loses a scenario or one scenario's time changes a lot, so fortnightly loses little against weekly; a run triggered by a change to `molecule-shards.yml` or to a role's scenario list, in addition to the schedule, would catch the one case that matters.

### Using the timings

- **A report only.** A tool reads the artifacts, takes each scenario's median over the runs it has, packs the scenarios longest-first into the same number of shards as the table has, and prints the table's longest shard next to the packed one. The maintainer changes the table when the gap is worth the change. Nothing is written back.
- **A report that also names roles to split or merge.** The same tool lists a non-split role whose total is above a limit, and a split role whose shards are all short. The table's role list then follows the data and not only the first measurement.
- **A pull request opened by the workflow.** Needs a token with `contents` and `pull-requests` write on the schedule's own run, the same class of credential the promotion checklist already limits to one workflow. A table change would also land with no one having read the measurements. The repo's rule that no unattended run holds more than it needs argues against it.

### The Python unit tests

- **Leave it, and record.** Add `--durations` and a JUnit file to a scheduled run so the growth is visible, and do nothing until the job is the longest in a pull request's run.
- **Run the tests in parallel with `pytest-xdist`.** One job, one check name, no table to keep. The balancing is done at run time by the plugin, so there is no timing record to maintain. The cost is a dependency, the order-and-shared-state risk above, and that a job on the runner's cores gains only as many as it has.
- **Split into a matrix on a timing table, like the Molecule shards.** Gives each group a stated time and fits the way the repo already works. Needs the same rebalance loop, the check-name change above, and about 15 seconds of setup a leg for a suite whose time is mostly three files. Groups cannot be better balanced than the largest test allows.
- **Make the slow tests faster.** The three files named above wait on real time or poll loops, and most of the suite is already fast. A fake clock or a short timeout where the wait is not the behaviour under test could cut about 100 seconds with no change to CI. The cost is the care to keep each test asserting what it asserted, and it does not help growth elsewhere.

## Leaning

Molecule: a scheduled full run that uploads one timings artifact per leg, plus the same artifact on pull request runs, and a report-only tool that proposes a table and names roles worth splitting; no write-back. Weekly at first, since the data is what decides whether fortnightly is enough.

Python: measure first. If `python-unit-tests` is shorter than the longest Molecule leg on the runner, do only the recording. If not, try `pytest-xdist` and fix the three slow files before building a second table, because the one measurement so far says the time sits in a few tests, which grouping cannot help.

What would change this: the runner's times for `python-unit-tests` and for Molecule scenarios turning out to be far less stable than the local numbers suggest (the median over runs is then the only usable figure), or a plan that charges for the scheduled run.
