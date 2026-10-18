---
id: PROJ-backup-agent-docker-api-rules
title: "Backup Agent Docker API Rules"
type: project
status: building
blocked: false
summary: "Give the backup agent's Docker socket proxy a rules file that allows only the calls the agent makes, in place of capability flags."
decision: ADR-0004/1
allowed_paths:
  - ansible/roles/backup_agent/**
  - docs/topics/disaster-recovery/backup.md
  - docs/topics/engineering/molecule-testing.md
---

# Backup Agent Docker API Rules

Replaces `backup_agent`'s `CONTAINERS=1 POST=1 INFO=1` proxy flags with a rules file that names the five calls the agent makes. It is staged because the file and its mount, the run on the real agent and the check of the allowed and refused calls each need their own run in CI.

## Scope

In: the rules file for `backup-dockerproxy` and its read-only mount over the image's template; removing the three flag lines; the Molecule run on the real agent; the Molecule check of the allowed and refused calls, on the real proxy image in front of a fake socket; the topic docs that name `POST=1` as the grant.

Not in: `beszel-agent`'s proxy, which stays on `CONTAINERS=1`; capability dropping on the proxy sidecar; the proxy image's pin or digest; any change to the five calls.

## Decision

Implements [ADR 0004 revision 1 (Docker API access)](../decisions/0004-container-access-to-the-docker-api/revision-001.md), `approved`; this doc tracks build status only.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Rules file and mount | Done | `backup-dockerproxy` mounts the rules file read-only over the image's template and sets no `CONTAINERS`, `POST` or `INFO`; the rendering checks assert both; the `backup_agent` scenarios pass `idempotence`. |
| 2 | Run on the real agent | Done | The `default` scenario still sees `happy_app_stop` stopped, backed up and started by its own schedule, through the proxy running the rules file. |
| 3 | Allowed and refused calls | Done | A Molecule step starts the real proxy image with the rules file in front of a fake socket that records what reaches it, and asserts each allowed call arrives unchanged and each refused call in the revision gets a 403 and never reaches the socket. |
| 4 | Topic docs | Done | [`backup.md`](../topics/disaster-recovery/backup.md) and [`molecule-testing.md`](../topics/engineering/molecule-testing.md) describe the rules file and the new assertions, and neither names `POST=1` as the backup agent's grant. |

Stages 2 and 3 are the first runs of the file on the pinned HAProxy 3.4.2 and the real agent. If either fails, stop and record a new assumption in the revision ([`README.md#stop-conditions`](README.md#stop-conditions)).

## Acceptance criteria

- [ ] `backup-agent-dockerproxy` reads no capability flag and runs from the rules file, which ends in `http-request deny`.
- [ ] The `backup_agent` `default` scenario passes on the real proxy and agent images with a stop-during-backup schedule, and the `no_stop_apps` scenario still renders no proxy.
- [ ] The allowed and refused calls listed in the revision behave as the revision states, on the real proxy image in front of a fake socket.
- [ ] The topic docs describe the rules file, and the proxy's remaining limit (any container can be stopped by id) is stated as it is.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the proxy image, its tag or digest; the five calls or the frontend in the revision (that is a change to the Decision); `docker/beszel-agent/**`; an app's `stop-during-backup` label.
- **Relevant files and interfaces:** [`compose.yaml.j2`](../../ansible/roles/backup_agent/templates/compose.yaml.j2); the `default` scenario's `verify_backup_behavior.yml` and `verify_compose_rendering.yml`; the image's entrypoint, which substitutes only `${BIND_CONFIG}` into `/usr/local/etc/haproxy/haproxy.cfg.template`.
- **Required checks:** `pre-commit run --all-files`; the `backup_agent` Molecule scenarios, which run in CI because they need the real images.

## Risks

- The rules file was exercised on HAProxy 3.4.0 and a fake socket only. A difference in 3.4.2's regex handling would show first in stage 3.
- The fake socket has to be a listener the proxy container can mount, started without a new image. If it needs one, that image falls under the digest pinning in [ADR 0083 (Images a deploy runs)](../decisions/0083-making-a-deploy-run-the-images-its-commit-names/revision-000.md) and is a scope change.
- The file copies the rest of upstream's `haproxy.cfg` at v0.5.0. A Renovate bump of the proxy image does not touch the copy, so a stale copy is caught only by review and the scenario.
- [`gatus-job-heartbeats.md`](gatus-job-heartbeats.md) also allows `ansible/roles/backup_agent/**`, so the two can conflict on the same files.

## Open items

- Whether `beszel-agent` gets its own rules file, as a follow-up to this project and not part of it. At Beszel 0.21.0 the agent also reads a container's inspect data and logs, `/info` and an image's inspect data, besides the list and stats, so a rules file would still admit the inspect and log reads. It would stop `archive`, `export` and the other read paths, and its call set moves with each Beszel release. Today's flags already refuse `/info` and the image calls.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
