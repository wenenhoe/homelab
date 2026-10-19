---
id: PROJ-backup-agent-compose-app
title: "Backup Agent As A Compose App"
type: project
status: not-started
blocked: false
summary: "Move the backup agent's compose file under docker/, declare the agent in each backup host's compose_apps, and deploy it through the compose role as a self-managed app."
decision: ADR-0088/0
allowed_paths:
  - docker/backup-agent/**
  - ansible/roles/backup_agent/**
  - ansible/roles/compose_app/tasks/main.yaml
  - ansible/inventory/group_vars/all/app_catalog.yaml
  - ansible/inventory/group_vars/all/main.yaml
  - ansible/inventory/host_vars/*.yaml
  - ansible/playbooks/cleanup.yaml
  - tools/ci/gates/app_catalog_rules.py
  - tools/tests/ci/gates/test_app_catalog_rules.py
  - .github/compose-boot-test-exclusions.txt
  - .github/renovate.json5
  - docs/topics/deploy/**
  - docs/topics/disaster-recovery/backup.md
  - docs/topics/engineering/conventions.md
  - docs/topics/engineering/molecule-testing.md
  - docs/topics/engineering/ci/gates.md
---

# Backup Agent As A Compose App

Moves the one stack that a role deploys from its own templates onto the path every other app takes: its compose file under `docker/`, a `compose_apps` entry on each host that runs it, and the `compose` role's tasks for the deploy. It is staged because the decision rests on two assumptions that a throwaway spike settles first, the move itself has to land as one change, and the result has to be checked on a real host before the work closes.

## Scope

In: `docker/backup-agent/` with the compose file and the proxy rules file; a catalog entry and the `compose_self_managed_apps` entry; the `compose_apps` entry on every host with a non-empty `backup_plan`; the role's restructure so it runs the `compose` role's `init` and `deploy` for its own entry and fails when a non-empty plan has none; the catalog validator's two-way check and its tests; the `backup_agent` scenarios taking the compose file by symlink; the boot-test exclusion; removing `backup-agent` from `compose_cleanup_exclude`; the topic docs that state any of this.

Not in: the files the role generates (`conf.d`, `.env`, the GPG key, the notification template, the freshness-check script and units), which stay in the role; when the agent deploys, what it backs up, and how it reaches SeaweedFS; `cloud-sync` and `openbao-backup`, which have no compose file; `ansible/roles/openbao/tasks/main.yaml` and `docs/topics/secrets/openbao.md`, which only name `compose_self_managed_apps`; `ansible/roles/compose/defaults/main.yaml`, which only names `compose_cleanup_exclude`; and `ansible/roles/compose/molecule/reset/verify.yml`, whose `backup-agent-like` fixture is a stand-in for any app with a backup.

## Decision

Implements [ADR 0088 (Role-deployed stack compose)](../decisions/0088-where-a-role-deployed-stack-compose-file-lives/revision-000.md), `working`; this doc tracks build status only. Stage 1 settles its two assumptions and sets it `approved`; no later stage starts before that.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Settle the decision's assumptions | Not started | For each host's `backup_plan`, the `compose` role renders `docker/backup-agent/compose.yaml.j2` to the bytes the role renders today and `docker compose config` agrees; a catalog entry with only `configs` passes the validator and the tests of every `resolved_apps` consumer; the revision has no open assumption and is `approved` |
| 2 | Move the stack and deploy it through the `compose` role | Not started | The compose file and rules file are under `docker/backup-agent/`; the catalog, `compose_self_managed_apps` and each backup host's `compose_apps` declare the agent; the role runs `init` and `deploy` for its own entry and fails when a non-empty plan has none; the validator fails a host with the entry and no plan, or a plan and no entry, with unit tests; the `backup_agent` scenarios deploy the symlinked file and pass in CI, including the rules file, its hash label and the absent proxy on a host with no stop-during-backup app; `backup-agent` is in the boot-test exclusion file and not in `compose_cleanup_exclude`; the topic docs describe the result |
| 3 | Roll out and verify | Not started | After the first deploy on a backup host, the agent and proxy containers keep their creation times, the end-of-run report lists `backup-agent` as ok, and `cleanup.yaml --check` proposes no change to it |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] No stack's compose file is outside `docker/<app>/`, Molecule fixtures aside.
- [ ] Each host with a non-empty `backup_plan` declares `backup-agent`, no other host does, and the validator fails a repository where that is untrue.
- [ ] The end-of-run report lists `backup-agent` on every backup host, and orphan cleanup has no special case for it.
- [ ] The rules file the proxy mounts equals its source in `docker/backup-agent/configs/`, and the sidecar's label changes when the file does.
- [ ] The first deploy after the change recreates no container.

## Agent handoff

Stop conditions are in [`README.md#stop-conditions`](README.md#stop-conditions); they apply without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the rules the proxy enforces, the schedules the agent runs, the SeaweedFS credentials it uses, and the files the role generates.
- **Relevant files and interfaces:** `ansible/roles/backup_agent/`, `ansible/roles/openbao/tasks/main.yaml` (the self-managed pattern to follow), `ansible/roles/compose/tasks/init.yaml` and `deploy.yaml`, `ansible/filter_plugins/backup_plan.py`, `tools/ci/gates/app_catalog_rules.py`.
- **Required checks:** `pre-commit run --all-files`; `uv run pytest` from `tools/`; `ansible-lint`; the `backup_agent`, `compose_app` and `compose` Molecule scenarios in CI; for stage 1, the render comparison the exit condition names.

## Risks

- A render that differs from today's, even in whitespace, recreates the agent and proxy on every host at the first deploy. Stage 1 exists to catch it before anything moves.
- The rules file is deployed to hosts that never start the proxy. It is a 0644 file with no secret in it.
- A host that gains a backed-up app without an entry fails in CI and at deploy time. That is the intent; nothing is skipped quietly.
- [`gatus-job-heartbeats.md`](gatus-job-heartbeats.md) also changes `ansible/roles/backup_agent/**` (the freshness check). The two do not depend on each other, but whichever merges second rebases over the other's edits to that role.
- [`bind-mounted-config-files.md`](bind-mounted-config-files.md) and this project both edit `app_catalog.yaml` and the deploy topic docs, and its stage 1 makes the `compose` role restart a container whose bind-mounted file changed. Once that lands, the proxy's hash label in the compose file duplicates it; stage 2 here drops the label only if it has.
- [`beszel-agent-docker-api-rules.md`](beszel-agent-docker-api-rules.md) names `ansible/roles/backup_agent/files/docker-api-rules.cfg` as its model, and its open item 1 asks how a rules file reaches the host. This project moves that file and answers it for `backup-agent`; stage 2 updates the mention in that doc in the same change, which `allowed_paths` does not bound (project docs are exempt).

## Open items

None beyond the two assumptions recorded in the decision.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
