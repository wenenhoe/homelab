# CI Scheduled Jobs

Every workflow with a `schedule` trigger. The PR pipeline is in [CI: PR Checks](pipeline.md).

## Schedule overview

Every workflow with a `schedule` trigger, listed by the time of day of its first tick in a week that starts on Sunday (UTC). Cron runs in UTC; Asia/Singapore is UTC+8 with no daylight saving. A tick is when GitHub queues the run, not when it starts: the start comes later by an unpredictable amount ([Renovate schedule window](#renovate-schedule-window) has the lag seen here). The image vulnerability assessment runs from another repo, so it has no row ([below](#image-vulnerability-assessment)).

| Workflow | Cron (UTC) | Fires (UTC) | Fires (Asia/Singapore) | What it does |
| :--- | :--- | :--- | :--- | :--- |
| `check-image-tags.yml` | `23 2 * * 0` | Sunday 02:23 | Sunday 10:23 | Checks that every pinned image still exists in its registry ([image tag check](image-tag-check.md)). |
| `check-release-checksums.yml` | `41 3 * * 0` | Sunday 03:41 | Sunday 11:41 | Asks each publisher again whether the pinned release hashes are theirs, and Docker and Tailscale whether they still serve the apt keys the roles pin ([release checksum check](release-checksum-check.md)). |
| `check-image-provenance.yml` | `13 4 * * 0` | Sunday 04:13 | Sunday 12:13 | Asks each publisher again whether the pinned image digests are theirs ([image provenance check](image-provenance-check.md)). |
| `check-shell-test-pins.yml` | `47 4 * * 0` | Sunday 04:47 | Sunday 12:47 | Checks that each pinned Bats release tag still points at its pinned commit ([shell test pins](../../testing/shell-test-pins.md#checking-the-pins)). |
| `scratch-gateway-qemu.yml` | `29 5 * * 0,3` | Sunday and Wednesday 05:29 | Sunday and Wednesday 13:29 | Boots the pinned OPNsense image in QEMU and runs the `rehearsal` spec on it, which also keeps the cached image from being evicted for going 7 days unused ([scratch gateway runs](../../infra/scratch-gateway-runs.md#the-workflow)). |
| `molecule-timings.yml` | `7 5 * * 3,6` | Wednesday and Saturday 05:07 | Wednesday and Saturday 13:07 | Times the Molecule scenarios of the roles whose files changed since they were measured and reports whether the shard table still balances them ([Molecule timings](../../testing/molecule-timings.md)). |
| `progress-log.yml` | `17 16 * * *` | Every day 16:17 | Every day 00:17 | Adds what was merged to `main` since the last run to the weekly and monthly progress log on the `progress-log` branch ([Progress log](#progress-log)). |
| `renovate.yml` | `37 17 * * *` | Every day 17:37 | Every day 01:37 | Runs Renovate, then checks that the run started inside its window ([Renovate schedule window](#renovate-schedule-window), [Renovate](renovate.md)). |
| `build-caddy-image.yml` | `0 20 * * 0` | Sunday 20:00 | Monday 04:00 | Rebuilds and pushes the Caddy image, as it does on a push that changes its Dockerfile ([Dockerfile changes](gates.md#dockerfile-changes)). |
| `build-gatus-image.yml` | `0 20 * * 0` | Sunday 20:00 | Monday 04:00 | Rebuilds and pushes the gatus image ([Dockerfile changes](gates.md#dockerfile-changes)). |
| `build-molecule-dind-image.yml` | `0 20 * * 0` | Sunday 20:00 | Monday 04:00 | Rebuilds and pushes the Molecule DinD image ([Dockerfile changes](gates.md#dockerfile-changes)). |
| `build-wastebin-image.yml` | `0 20 * * 0` | Sunday 20:00 | Monday 04:00 | Rebuilds and pushes the wastebin image ([Dockerfile changes](gates.md#dockerfile-changes)). |
| `trivy-scheduled.yml` | `0 20 * * 0` | Sunday 20:00 | Monday 04:00 | Report-only Ansible misconfiguration and secret scan ([Trivy security scans](#trivy-security-scans)). |
| `warm-caches.yml` | `0 20 * * 0,3` | Sunday and Wednesday 20:00 | Monday and Thursday 04:00 | Restores the `main` caches so GitHub doesn't evict them for going 7 days unaccessed ([base-branch warming](pipeline.md#base-branch-warming)). |

A workflow that gains, loses or changes a `schedule` trigger changes its row in the same pull request. No check compares this table to the workflows.

To see a workflow's recent runs, or run it now (each of these accepts `workflow_dispatch`):

```bash
workflow=check-image-tags.yml
gh run list --workflow "$workflow" --limit 5
```

```bash
workflow=check-image-tags.yml
gh workflow run "$workflow"
```

## Renovate schedule window

`renovate.json5`'s `schedule` only lets Renovate open new branches and PRs
inside a window, in its `timezone`. GitHub starts a scheduled run some
unpredictable time after its cron tick (1h44m to 2h20m observed here), so a
run can land after the window closed and open nothing while still
succeeding. `renovate.yml`'s last step,
[`tools/ci/gates/renovate_window.py`](../../../../tools/ci/gates/renovate_window.py),
turns that into a failure, which GitHub's failed-workflow notification then
surfaces.

The timezone and every `schedule:` array are read from `renovate.json5`, so
editing the window there changes what the check enforces. A run fails when
it started on a day the schedule has a window but outside that window's
hours; on any other day nothing is expected of it. It runs only for
`schedule` events (a manual `workflow_dispatch` isn't waiting on a cron
tick) and under `if: always()`, so it stays distinct from a Renovate
failure. Cron fields support `*`, ranges, lists and steps; minutes must be
`*`, as Renovate requires, and day names aren't supported.

## Trivy security scans

Report-only Ansible-misconfig and secret scanning, separate from the
correctness/linting jobs in [CI: PR Checks](pipeline.md#jobs) — see
[`security-scanning.md`](../../security/policy/security-scanning.md).

## Weekly pin checks

The four `check-*.yml` workflows in the table run weekly and on demand. The release checksum, image provenance and shell test pin checks are the ones the `release-checksums`, `provenance` and `shell-tests` PR jobs run when a pin changes, and what each verifies and how it fails is in the page its row links. GitHub emails a failed scheduled run to the person who last changed the schedule.

## Progress log

`progress-log.yml` runs daily and on demand. It reads `main`'s history since the last commit it recorded, updates the weekly and monthly files, and pushes them to the `progress-log` branch; [ADR 0095 (Progress log)](../../../decisions/0095-recording-what-was-worked-on-each-week-and-month/revision-000.md) decides what it reads, where it writes and why, and [Progress Log](../../documentation/progress-log.md) says how to read and rebuild it. It is the one workflow here that holds a write token: `contents: write` is on its `publish` job alone, and the job pushes to `progress-log` and nowhere else, with a plain push to a branch that must already exist, so a rejected push fails the run. Nothing goes to `main`, and a day with nothing new pushes nothing. GitHub emails a failed scheduled run to the person who last changed the schedule.

## Image vulnerability assessment

Runs once a week from the private `homelab-security` repo (its schedule ticks daily
and the first tick of each week runs), not from a workflow in this repo, and writes
nothing here. What it reads from this repo, how it ranks images
and what it doesn't cover are in
[`security-scanning.md`](../../security/policy/security-scanning.md#image-vulnerability-assessment).
