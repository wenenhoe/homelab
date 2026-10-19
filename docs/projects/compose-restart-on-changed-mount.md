---
id: PROJ-compose-restart-on-changed-mount
title: Restart on a Changed Bind-Mounted File
type: project
status: not-started
blocked: false
summary: The compose role restarts a container when a file bind-mounted into it changes, and nothing else.
decision: ADR-0087/0
allowed_paths:
  - ansible/roles/compose/**
  - docs/topics/deploy/**
  - docs/topics/engineering/molecule-testing.md
---

# Restart on a Changed Bind-Mounted File

The mechanism [ADR 0087 (Ansible-rendered files in containers)](../decisions/0087-delivering-files-ansible-renders-to-a-container/revision-000.md) needs before any app's file can move from a volume to a read-only bind mount: when a deploy changes a direct config or script that a container mounts, that container restarts in the same run. It is its own project because other work depends on the mechanism alone ([`backup-agent-compose-app.md`](backup-agent-compose-app.md)), and moving each app's files is [`bind-mounted-config-files.md`](bind-mounted-config-files.md).

## Scope

The `compose` role's change detection for direct configs and scripts, its Molecule scenario, and the rule stated in `docs/topics/deploy/volumes.md`. Not in scope: moving any app's file out of a volume ([`bind-mounted-config-files.md`](bind-mounted-config-files.md)).

## Decision

Implements [ADR 0087 (Ansible-rendered files in containers)](../decisions/0087-delivering-files-ansible-renders-to-a-container/revision-000.md), `approved`; this doc tracks build status only. [`bind-mounted-config-files.md`](bind-mounted-config-files.md) names the same revision and is the last to close, so it accepts it.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Restart on a changed bind-mounted file | Not started | A changed direct config or script restarts the container that mounts it in the same run and restarts nothing else; a `compose` Molecule scenario asserts the container reads the new content and that a second run changes nothing; `volumes.md` states the rule and what stays a volume |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] A deploy that changes a file a container mounts restarts that container and no other, and the container reads the new content.
- [ ] A second deploy with no change restarts nothing.
- [ ] `docs/topics/deploy/volumes.md` states the rule and what stays a volume.
- [ ] `pre-commit run --all-files` passes.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** any ADR revision beyond the edits [`docs/decisions/README.md#assumptions`](../decisions/README.md#assumptions) permits; the Decision of ADR 0087; any volume an app writes to; the Docker socket mounts.
- **Relevant files and interfaces:** `ansible/roles/compose/tasks/init.yaml` and `deploy.yaml` for the change roll-up and the direct deploy path; `docs/topics/deploy/volumes.md` for what exists now.
- **Required checks:** `pre-commit run --all-files`; the `compose` role's Molecule scenarios.

## Risks

- A second mechanism that recreates the container on a changed file would restart it twice with the roll-up; the stage picks one.

## Open items

None.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
