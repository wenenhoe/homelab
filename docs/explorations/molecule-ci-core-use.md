---
id: EXP-molecule-ci-core-use
title: "Should a Molecule leg in CI use more than one of its runner's cores?"
type: exploration
status: open
summary: "Whether CI's Molecule legs run scenarios side by side, given what that does to the timings the shard table is balanced on."
topic: repository-tooling
related: [ADR-0115]
---

# Should a Molecule leg in CI use more than one of its runner's cores?

Each `molecule` leg runs its scenarios one at a time on a machine with several cores. [`molecule-test-all.sh -j`](../topics/testing/molecule-testing.md#running-scenarios) can run them side by side, and whether CI should is open: it has not been tried with real scenarios on a runner, and the shard table rests on times taken one at a time.

## What bears on it

- A [standard GitHub-hosted Linux runner](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) for a public repository has 4 CPUs, 16 GB of memory and 14 GB of disk. Side by side, scenarios share the disk as well as the cores, and each pulls its images into it.
- A run takes as long as its slowest leg. [Shards](../topics/engineering/ci/pipeline.md#sharded-roles) already split the slow roles across runners.
- The shard table is balanced on [measured times](../topics/testing/molecule-timings.md) of scenarios run one at a time ([ADR 0115](../decisions/0115-keeping-the-molecule-shard-table-balanced/revision-000.md)). Times taken side by side include contention, so the script refuses to write them.
- Scenario instance names are unique across roles and no scenario publishes a port. Most set `cgroupns_mode: host`, so their systemd containers share the runner's cgroup tree.
- Each scenario writes its own coverage data file, so the [coverage gate](../topics/engineering/ci/gates.md#molecule-coverage-gate) reads the same data either way.
- With `-j`, a failure starts no further scenario of that role, while those already running finish.

## Options

- **Leave the legs as they are.** Nothing to build or keep right. The cores stay idle.
- **`-j` within the existing shards.** Shortens the slowest legs if the scenarios do not contend much. The timing run would still measure one at a time, so the table would be balanced on numbers CI no longer runs at.
- **`-j` with fewer legs.** Saves each removed leg's setup too. The table and ADR 0115 would need to describe a leg by something other than a sum of times.

## Still to check

- Whether scenarios of one role, and of different roles, pass side by side on one daemon, and how often they fail only that way.
- The time a leg of two or four saves against its summed serial times.
- The disk and memory a leg of the heaviest scenarios needs side by side.

## Leaning

Try `-j` on a workstation and in a cloud session first. CI follows only if the saving on the slowest leg is large and the runs are as reliable as serial ones.
