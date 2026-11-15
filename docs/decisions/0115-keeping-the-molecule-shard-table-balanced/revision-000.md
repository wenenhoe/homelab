---
id: ADR-0115
revision: 0
type: adr
title: Keeping the Molecule shard table balanced as scenarios change
short: Molecule shard balance
solution: A scheduled run times only the roles whose files changed, keeps the numbers in the Actions cache, and reports a better table without writing it
summary: How the shard table in .github/molecule-shards.yml learns when scenarios are added, removed or slowed, without running every scenario on every schedule.
topic: repository-tooling
status: accepted
weight: light
related: [ADR-0064]
---

# 0115. Keeping the Molecule shard table balanced as scenarios change

## Problem

The shard table was balanced once, on measured scenario times. A scenario added to a split role, a role that grows past the longest leg, or a scenario that gets slower is invisible until someone reads a job summary, which cannot be collected. The table must be re-balanced from measurements that stay current, at a cost in runner time that follows what changed and not the calendar.

## Context

- A pull request runs only the roles its diff queues, by each role's watch set ([Molecule watch sets](../../topics/engineering/ci/change-scoping.md#molecule-watch-sets)), so timings taken from pull requests describe the roles that change most.
- A run of every scenario is the only complete measurement, and most scheduled runs would repeat numbers that cannot have moved.
- A workflow can neither commit nor open a pull request without a credential that writes to the repository, and a table change is wanted only after someone has read the numbers.
- The Actions cache restores by key prefix, counts a restore as access, and evicts an entry unused for 7 days.

## Decision

[`molecule-timings.yml`](../../../.github/workflows/molecule-timings.yml) runs twice a week. Each role has a fingerprint, the content of every file in its watch set and the paths every scenario inherits, so a role needs timing again exactly when a pull request touching those files would have queued it. A role is also timed again when its measurement is 90 days old, which catches a runner that changed without the repo changing. Only those roles run, as the same legs a pull request uses. Their timings, with the fingerprints, are kept in one JSON file in the Actions cache, and a report compares the table with them and proposes a better one. The report writes nothing back: the maintainer changes the table by a pull request.

## Alternatives considered

- **Time every scenario on every run.** Complete and simple. It repeats most of its work.
- **Keep the state in the repository.** Needs a write credential on a schedule, and puts a generated file in history. The cache loses its entry after 7 idle days at worst, and the next run measures everything again.
- **Take the timings from pull request runs only.** Costs nothing, and leaves rarely changed roles unmeasured.
- **Open the pull request from the workflow.** A table change nobody has read, behind a credential the schedule would otherwise not need.

## Reconsideration triggers

Runner times too unstable for one measurement per fingerprint to mean anything; a cache that is evicted often enough that most runs measure every role; a plan that charges for the scheduled run.
