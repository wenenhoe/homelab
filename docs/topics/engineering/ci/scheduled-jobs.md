# CI Scheduled Jobs

Checks that run on a schedule: the Renovate window check, the Trivy scans (which also run as a PR job), the release checksum check (which does too), the shell test pin check and the progress log. The PR pipeline is in [CI: PR Checks](pipeline.md). The [schedule overview](#schedule-overview) lists every scheduled workflow and when it fires. The weekly image vulnerability assessment is scheduled too, but from the private `homelab-security` repo's CI, so no workflow here runs it; see below.

## Schedule overview

Every workflow with a `schedule` trigger, listed by the time of day of its first tick in a week that starts on Sunday (UTC). Cron runs in UTC; Asia/Singapore is UTC+8 with no daylight saving. A tick is when GitHub queues the run, not when it starts: the start comes later by an unpredictable amount ([Renovate schedule window](#renovate-schedule-window) has the lag seen here). The image vulnerability assessment runs from another repo, so it has no row ([below](#image-vulnerability-assessment)).

| Workflow | Cron (UTC) | Fires (UTC) | Fires (Asia/Singapore) | What it does |
| :--- | :--- | :--- | :--- | :--- |
| `check-image-tags.yml` | `23 2 * * 0` | Sunday 02:23 | Sunday 10:23 | Checks that every pinned image still exists in its registry ([image tag check](image-tag-check.md)). |
| `check-release-checksums.yml` | `41 3 * * 0` | Sunday 03:41 | Sunday 11:41 | Asks each publisher again whether the pinned release hashes are theirs ([release checksum check](release-checksum-check.md)). |
| `check-image-provenance.yml` | `13 4 * * 0` | Sunday 04:13 | Sunday 12:13 | Asks each publisher again whether the pinned image digests are theirs ([image provenance check](image-provenance-check.md)). |
| `check-shell-test-pins.yml` | `47 4 * * 0` | Sunday 04:47 | Sunday 12:47 | Checks that each pinned Bats release tag still points at its pinned commit ([shell test pins](shell-test-pins.md#checking-the-pins)). |
| `progress-log.yml` | `17 16 * * *` | Every day 16:17 | Every day 00:17 | Adds what was merged to `main` since the last run to the weekly and monthly progress log on the `progress-log` branch ([Progress log](#progress-log)). |
| `renovate.yml` | `37 17 * * *` | Every day 17:37 | Every day 01:37 | Runs Renovate, then checks that the run started inside its window ([Renovate schedule window](#renovate-schedule-window), [Renovate](renovate.md)). |
| `build-caddy-image.yml` | `0 20 * * 0` | Sunday 20:00 | Monday 04:00 | Rebuilds and pushes the Caddy image, as it does on a push that changes its Dockerfile ([Dockerfile changes](gates.md#dockerfile-changes)). |
| `build-coderabbit-review-image.yml` | `0 20 * * 0` | Sunday 20:00 | Monday 04:00 | Rebuilds and pushes the CodeRabbit review image ([Dockerfile changes](gates.md#dockerfile-changes)). |
| `build-gatus-image.yml` | `0 20 * * 0` | Sunday 20:00 | Monday 04:00 | Rebuilds and pushes the gatus image ([Dockerfile changes](gates.md#dockerfile-changes)). |
| `build-molecule-dind-image.yml` | `0 20 * * 0` | Sunday 20:00 | Monday 04:00 | Rebuilds and pushes the Molecule DinD image ([Dockerfile changes](gates.md#dockerfile-changes)). |
| `build-wastebin-image.yml` | `0 20 * * 0` | Sunday 20:00 | Monday 04:00 | Rebuilds and pushes the wastebin image ([Dockerfile changes](gates.md#dockerfile-changes)). |
| `trivy-scheduled.yml` | `0 20 * * 0` | Sunday 20:00 | Monday 04:00 | Report-only Ansible misconfiguration and secret scan ([Trivy security scans](#trivy-security-scans)). |
| `warm-caches.yml` | `0 20 * * 0,3` | Sunday and Wednesday 20:00 | Monday and Thursday 04:00 | Restores the `main` caches so GitHub doesn't evict them for going 7 days unaccessed ([base-branch warming](pipeline.md#base-branch-warming)). |

A workflow that gains, loses or changes a `schedule` trigger changes its row in the same pull request. No check compares this table to the workflows.

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
[`security-scanning.md`](../security-scanning.md).

## Release checksum check

`check-release-checksums.yml` runs weekly and on demand,
asking each publisher again whether the pinned release hashes are theirs. It
is the same check the `release-checksums` PR job runs when a pin changes; what
it verifies and how it fails is in
[CI Release Checksum Check](release-checksum-check.md). GitHub emails a failed scheduled
run to the person who last changed the schedule.

## Image provenance check

`check-image-provenance.yml` runs weekly and on demand, asking each publisher
again whether the pinned image digests are theirs. It is the same check the
`provenance` PR job runs when an image reference changes; what it verifies and how
it fails is in [CI Image Provenance Check](image-provenance-check.md). GitHub
emails a failed scheduled run to the person who last changed the schedule.

## Shell test pin check

`check-shell-test-pins.yml` runs weekly and on demand, asking GitHub again
whether each pinned Bats release tag still points at its pinned commit. It is
the same check the `shell-tests` PR job runs when the pin file or its tooling
changes; what it verifies and how it fails is in
[CI Shell Test Pins](shell-test-pins.md#checking-the-pins). GitHub emails a
failed scheduled run to the person who last changed the schedule.

## Progress log

`progress-log.yml` runs daily and on demand. It reads `main`'s history since the last commit it recorded, updates the weekly and monthly files, and pushes them to the `progress-log` branch; [ADR 0095 (Progress log)](../../../decisions/0095-recording-what-was-worked-on-each-week-and-month/revision-000.md) decides what it reads, where it writes and why, and [Progress Log](../progress-log.md) says how to read and rebuild it. It is the one workflow here that holds a write token: `contents: write` is on its `publish` job alone, and the job pushes to `progress-log` and nowhere else, with a plain push to a branch that must already exist, so a rejected push fails the run. Nothing goes to `main`, and a day with nothing new pushes nothing. GitHub emails a failed scheduled run to the person who last changed the schedule.

## Image vulnerability assessment

Runs once a week from the private `homelab-security` repo (its schedule ticks daily
and the first tick of each week runs), not from a workflow in this repo, and writes
nothing here. What it reads from this repo, how it ranks images
and what it doesn't cover are in
[`security-scanning.md`](../security-scanning.md#image-vulnerability-assessment).
