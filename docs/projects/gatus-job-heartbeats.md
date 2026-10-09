---
id: PROJ-gatus-job-heartbeats
title: "Gatus Job Heartbeats"
type: project
status: not-started
blocked: false
summary: "Replace Uptime Kuma push monitors with Gatus external endpoints: one declared endpoint and generated token per job."
decision: ADR-0072/0
allowed_paths:
  - docker/gatus/**
  - docker/uptime-kuma/**
  - docker/openbao/watcher/**
  - docker/dashy/configs/conf.yaml.j2
  - .github/workflows/build-gatus-image.yml
  - .github/image-smoke-tests/gatus.sh
  - .github/renovate.json5
  - tools/ci/images/registry.py
  - tools/ci/fixtures/preseed_manual_secrets.py
  - tools/tests/ci/images/**
  - tools/tests/ci/scope/test_compose_apps.py
  - tools/tests/ci/scope/test_molecule_scope.py
  - ansible/inventory/group_vars/all/app_catalog.yaml
  - ansible/inventory/group_vars/all/main.yaml
  - ansible/inventory/group_vars/all/secret_catalog.yaml
  - ansible/inventory/host_vars/*.yaml
  - ansible/ci-inventory/group_vars/all/ci_dummy_vars.yaml
  - ansible/playbooks/deploy.yaml
  - ansible/roles/uptime_kuma_push/**
  - ansible/roles/gatus_push/**
  - ansible/roles/step_ca_cert/**
  - ansible/roles/cloud_sync/**
  - ansible/roles/caddy_cert_expiry/**
  - ansible/roles/backup_agent/**
  - ansible/roles/systemd_reload/**
  - docs/topics/monitoring/**
  - docs/topics/README.md
  - docs/topics/deploy/ansible.md
  - docs/topics/disaster-recovery/backup.md
  - docs/topics/disaster-recovery/restore.md
  - docs/topics/engineering/ci/gates.md
  - docs/topics/engineering/molecule-testing.md
  - docs/topics/engineering/nist-800-53-alignment.md
  - docs/topics/secrets/cloud-credentials/rotation.md
  - docs/topics/secrets/openbao.md
  - docs/topics/secrets/openbao-r2-read-watcher.md
  - docs/topics/secrets/openbao-reinit-runbook.md
  - docs/architecture/secrets-and-credentials-flow.md
---

# Gatus Job Heartbeats

Replaces the Uptime Kuma push monitors with Gatus external endpoints, so every job's monitor, token and alert routing is declared in the repo and not created by hand in a UI. It is staged because the image pipeline, the app, every producer, the certificate-renewer liveness change and the removal each ship and verify on their own, and the two monitors run side by side before Kuma goes.

## Scope

In: a repo-built Gatus image; the `gatus` app on `security`, where Kuma runs; one external endpoint and generated token per job (the three `backup_agent` hosts, the four `cert-expiry-check` hosts, `cloud_sync`, the two `cert-renewer@` instances, and the `r2-read-watcher` heartbeat); the daily `cert-renewer@` liveness push; a parallel run; removing Kuma.

Not in: moving the monitor to another host or off-site ([`monitoring-host-isolation.md`](monitoring-host-isolation.md), [`off-site-monitoring.md`](off-site-monitoring.md)); active probing beyond the one self-probe; replacing Beszel; changing any `OnFailure=` route, which stays as it is.

## Decision

Implements [ADR 0072 (Job heartbeats)](../decisions/0072-detecting-scheduled-jobs-that-stop-running/revision-000.md), `approved`; this doc tracks build status only.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Thin Gatus image and its pipeline | Not started | The image builds and pushes from CI as non-root with a working healthcheck, its smoke test passes, Renovate bumps its `FROM`, and the registry accepts the upstream `v`-prefixed tag and publishes it without the `v`, with unit tests |
| 2 | Gatus app on `security` beside Kuma | Not started | Gatus runs with the self-probe, per-group Telegram overrides and a gated dashboard; its route skips forward-auth; one endpoint per job is rendered from the repo with a generated token; `gatus.md` describes it |
| 3 | Producers push to Gatus as well as Kuma | Not started | `cloud_sync`, `cert-expiry-check`, the backup freshness check and the `r2-read-watcher` heartbeat each send the `POST` with a bearer header to their Gatus endpoint besides their Kuma push, and every such endpoint has a result |
| 4 | `cert-renewer@` daily liveness push | Not started | Each instance's timer pushes once a day only when `step certificate needs-renewal --expires-in <margin>` exits 1, with the margin chosen, and a test covers each exit code; the `OnSuccess=` link is gone |
| 5 | Parallel run | Not started | Over one full cycle of the longest endpoint interval, no endpoint false-alerts; one job per Telegram topic is stopped on purpose and alerts in its own topic within two intervals, and the next push resolves it |
| 6 | Remove Kuma | Not started | Nothing pushes to Kuma; its app, route, dashboard link, secrets entries, role code and doc are gone; the push role has a neutral name; the two monitoring project docs name Gatus |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 3 and 5 notes

Two things make the parallel run safe. Kuma's push monitors keep their own intervals and are left untouched, so a Gatus problem cannot silence them. And Gatus restarts its heartbeat timing on any config change, so the endpoint list is rendered once and changed rarely during the run: a change defers detection by up to one interval.

## Acceptance criteria

- [ ] Every job that pushed to Kuma has a Gatus external endpoint declared from the repo with its own generated token, and no monitor, token or notification setting exists only inside a running instance.
- [ ] A job that stops pushing alerts in its own Telegram topic within two of its intervals, and the next push resolves the alert.
- [ ] A certificate that stops being renewed raises an alert while it is still valid.
- [ ] The dashboard requires login, and the push path does not go through forward-auth.
- [ ] The image is built in this repo, runs non-root with a passing healthcheck, and its compose pin equals the registry's tag.
- [ ] Kuma, its role code, its secrets entries, its route and its doc are gone, and no file outside ADR history names it.
- [ ] `pre-commit run --all-files` passes.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** any ADR revision beyond the edits [`docs/decisions/README.md#assumptions`](../decisions/README.md#assumptions) permits; the `OnFailure=` routes and the `telegram-notify@` units; Kuma's data volume and monitors before stage 6; the Decision of ADR 0072.
- **Relevant files and interfaces:** `docker/wastebin/Dockerfile`, `.github/workflows/build-wastebin-image.yml` and the wastebin entry in `tools/ci/images/registry.py` as the pattern for a thin repo-built image; `ansible/roles/uptime_kuma_push/` and `docker/openbao/watcher/` for the push units; `ansible/roles/step_ca_cert/templates/cert-renewer@.service.j2` and its timer; `docs/topics/monitoring/uptime-kuma.md` for what exists now.
- **Required checks:** `pre-commit run --all-files`; the Molecule scenario of every role a stage touches; `ci.images` unit tests for stage 1; the Dockerfile build check and smoke test for the Gatus image.

## Risks

- A changed Gatus config restarts every heartbeat timer, so a batch of config changes during the parallel run can defer detection by up to one interval each; keep them few.
- The `v`-prefix change is in shared image-registry code that every repo-built image uses, so stage 1 needs its tests to cover the existing entries unchanged.
- Gatus's image is a thin layer over an upstream image, so a stale upstream shows up here until Renovate's bump lands.

## Open items

- **Backup of Gatus's sqlite volume.** It holds history and open-incident state, not secrets or configuration. Whether it is backed up follows the per-app defaults in [ADR 0068 (Backup defaults)](../decisions/0068-where-per-app-backup-settings-get-their-defaults/revision-000.md); decide in stage 2.
- **The `cert-renewer@` margin.** It must exceed two daily intervals, about 52 hours with slack; stage 4 picks the value.
- **Older ADRs that name Kuma.** ADRs 0012, 0026, 0042, 0045, 0047, 0049 and 0068 describe Kuma as it was when each was decided. Whether any gets a new revision is a decision for a human, outside this project's paths.
- **Where Gatus runs.** It lands on `security`, beside Kuma, as that is where the monitor runs today. Moving it is the other two monitoring projects' work, and stage 6 updates their text to say Gatus.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
