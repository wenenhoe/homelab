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

Each `molecule` leg runs its scenarios one at a time on a machine with several cores. [`molecule-test-all.sh -j`](../topics/testing/molecule-testing.md#running-scenarios) can run them side by side, and whether CI should is open: it has run real scenarios on a workstation, untimed, and none on a runner, and the shard table rests on times taken one at a time.

## What bears on it

- A [standard GitHub-hosted Linux runner](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) for a public repository has 4 CPUs, 16 GB of memory and 14 GB of disk. Side by side, scenarios share the disk as well as the cores, and each pulls its images into it.
- A run takes as long as its slowest leg. [Shards](../topics/engineering/ci/pipeline.md#sharded-roles) already split the slow roles across runners.
- The shard table is balanced on [measured times](../topics/testing/molecule-timings.md) of scenarios run one at a time ([ADR 0115](../decisions/0115-keeping-the-molecule-shard-table-balanced/revision-000.md)). Times taken side by side include contention, so the script refuses to write them.
- Scenario instance names are unique across roles and no scenario publishes a port. Most set `cgroupns_mode: host`, so their systemd containers share the runner's cgroup tree.
- Each scenario writes its own coverage data file, so the [coverage gate](../topics/engineering/ci/gates.md#molecule-coverage-gate) reads the same data either way.
- With `-j`, a failure starts no further scenario of that role, while those already running finish.

## What a cloud session showed

A [cloud session](../topics/engineering/hosted-sessions.md) has 4 cores and 15 GB of memory, like a runner, with one Docker daemon. One run of each, serial against `-j 4`:

| Scenarios | Serial | `-j 4` | Speedup |
| :--- | :--- | :--- | :--- |
| the 7 of `compose` | 948 s | 292 s | 3.2× |
| the 8 of `compose_app`, `bind9` and `caddy` | 885 s | 487 s | 1.8× |

Every scenario passed both ways, the coverage floors held, and the two scenarios of `compose` that fail on purpose failed the same way in both. Free memory stayed above 11 GB, disk use rose by 3 GB to 12 GB, and CPU use peaked at 91% to 94%. The second set is bounded by its longest scenario, `bind9`'s `secondary` at 288 s, which no `-j` shortens.

## Options

- **Leave the legs as they are.** Nothing to build or keep right. The cores stay idle.
- **`-j` within the existing shards.** Shortens the slowest legs if the scenarios do not contend much. The timing run would still measure one at a time, so the table would be balanced on numbers CI no longer runs at.
- **`-j` with fewer legs.** Saves each removed leg's setup too. The table and ADR 0115 would need to describe a leg by something other than a sum of times.

## Still to check

- Whether scenarios of different roles pass side by side on one daemon on a runner, and how often, over many runs, they fail only that way. One run in a cloud session did not.
- The time a leg of two saves against its summed serial times, and a leg of four on a runner.
- The disk and memory a leg of the heaviest scenarios, such as those of `secrets` or `host_hardening`, needs side by side.

## Leaning

Time `-j` on a runner next, in a leg of a pull request that can be thrown away. The cloud session's saving is large when a leg holds many short scenarios and small when one scenario dominates, so CI follows only if the saving on the slowest leg is large and the runs are as reliable as serial ones.
