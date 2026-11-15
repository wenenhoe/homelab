# CI Molecule Timings

How the shard table in [`.github/molecule-shards.yml`](../../../../.github/molecule-shards.yml) is kept balanced: a scheduled run times the scenarios of the roles that changed, records the numbers, and reports a better table. The table's use in the pipeline is in [CI: PR Checks](pipeline.md#sharded-roles); the decision is [ADR 0115 (Molecule shard balance)](../../../decisions/0115-keeping-the-molecule-shard-table-balanced/revision-000.md).

[`molecule-timings.yml`](../../../../.github/workflows/molecule-timings.yml) fires on Wednesday and Saturday at 05:07 UTC and on demand. Its `force` input measures every role. The code is `tools/ci/timing/`, run from `tools/` through `uv run`.

## What gets timed

`ci.timing.fingerprint` gives each role a digest of the files its Molecule run reads: its [watch set](change-scoping.md#molecule-watch-sets) plus the paths every scenario inherits, as `git ls-files -s` lists them. The digest follows content, so a rebuilt checkout of the same files gives the same one. A role needs timing again when it has no record, its digest differs from the recorded one, or its record is more than 90 days old. `ci.timing.plan` names those roles, and the `plan` job turns them into legs with `ci.scope.molecule_shards`, the same legs a pull request runs. A run on a quiet week names none, so the `measure` job is skipped and only the report runs.

## What is recorded

One JSON file, `state.json`: for each role its digest, the date measured and the seconds each scenario took. It lives in the Actions cache under `molecule-timings-<run id>-<attempt>`, and a run restores the newest entry by that prefix. A restore counts as access, so two runs a week keep it clear of the 7-day eviction. A missing, unreadable or differently versioned file reads as empty, and the run measures every role.

Each leg runs `molecule-test-all.sh` with `MOLECULE_TIMINGS_FILE` set, which writes one tab-separated row per scenario that ran (role, scenario, seconds, result), including a failed one, and uploads it under a name of its own, so the legs' files never replace one another when downloaded. `ci.timing.merge` records a role only when every scenario on disk was timed and passed: a failed scenario's time is the time to the failure, and a partial set would make a shard look faster than it is. A scenario timed twice, or a role the run was meant to time that sent no file, is reported the same way, in the job summary and as a warning. A role it cannot record keeps its old entry, which no longer matches its digest, so the next run takes it again. A leg that fails fails the workflow; the other legs' timings are still recorded.

## The report

`ci.timing.report` writes a table to the job summary and, when anything should change, `molecule-shards.proposed.yml` to the `molecule-timings` artifact (kept 30 days), next to `state.json`. For each measured role it packs the scenarios longest first into the least loaded shard, in as many shards as fit the target of 10 minutes a leg, and reports the role when:

- its longest leg is past the target and the new layout shortens it by at least 30 seconds and 10%;
- fewer legs would hold it within the target, which saves about 15 seconds of setup for each leg dropped;
- it has as many legs as it needs and a repack shortens the longest by the same margin.

A role whose slowest scenario alone is over the target is shown with that scenario as the floor: no table gets it lower. The proposal is in the table's own format. A role that would need only one leg is a comment, since the table lists split roles only.

Nothing writes the table. To apply a proposal, change `.github/molecule-shards.yml` in a pull request; `detect-changes` and `test_molecule_shards.py` check that it covers each scenario exactly once.

## Reading the numbers

Times are the runner's, so a leg's time moves with its load; the 30-second and 10% margins keep a repack from following that noise. A measurement is taken once per digest, not averaged. A change that touches a shared path (the Galaxy requirements, `ansible.cfg`, the coverage callback) changes every digest and so measures every role once.
