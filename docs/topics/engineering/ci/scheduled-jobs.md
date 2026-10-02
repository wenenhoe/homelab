# CI Scheduled Jobs

Checks that run on a schedule: the Renovate window check, and the Trivy scans (which also run as a PR job). The PR pipeline is in [CI: PR Checks](pipeline.md). The weekly image vulnerability assessment is scheduled too, but from the private `homelab-security` repo's CI, so no workflow here runs it; see below.

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

## Image vulnerability assessment

Runs weekly from the private `homelab-security` repo, not from a workflow in this
repo, and writes nothing here. What it reads from this repo, how it ranks images
and what it doesn't cover are in
[`security-scanning.md`](../security-scanning.md#image-vulnerability-assessment).
