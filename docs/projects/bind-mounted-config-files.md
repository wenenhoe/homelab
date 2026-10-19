---
id: PROJ-bind-mounted-config-files
title: "Bind-Mounted Config Files"
type: project
status: not-started
blocked: false
summary: "Mount files Ansible renders read-only from the stack directory, so a config file no longer needs a volume of its own."
decision: ADR-0087/0
depends_on:
  - project: PROJ-compose-restart-on-changed-mount
    reason: an app's file can move to a bind mount only once a change to it restarts its container
allowed_paths:
  - docker/caddy/**
  - docker/step-ca/**
  - docker/openbao/**
  - docker/minecraft/**
  - docker/seaweedfs/**
  - ansible/inventory/group_vars/all/app_catalog.yaml
  - ansible/roles/compose/**
  - ansible/roles/caddy/**
  - ansible/roles/step_ca_cert/molecule/signal_chown/**
  - ansible/tests/test_resolved_apps_consumers.py
  - docs/topics/deploy/**
  - docs/topics/services/caddy.md
  - docs/topics/services/step-ca.md
  - docs/topics/secrets/openbao.md
  - docs/topics/disaster-recovery/backup.md
  - docs/topics/engineering/molecule-testing.md
---

# Bind-Mounted Config Files

Moves the files Ansible renders for a container out of volumes and into read-only bind mounts, following [ADR 0087 (Ansible-rendered files in containers)](../decisions/0087-delivering-files-ansible-renders-to-a-container/revision-000.md). The restart on a changed mounted file is [`compose-restart-on-changed-mount.md`](compose-restart-on-changed-mount.md), which lands first; this project then moves each app's files, and each app ships and verifies on its own.

## Scope

In: the Caddyfile; `step-ca`'s `entrypoint.sh`; OpenBao's `openbao.hcl`; Minecraft's `modrinth-mods.txt`; SeaweedFS's `s3-identity.json`; removing the volumes those files no longer need, from the catalog, the compose files and running hosts.

Not in: the compose role's change detection for direct configs and scripts ([`compose-restart-on-changed-mount.md`](compose-restart-on-changed-mount.md)); `bind9`'s config, the `certs` volumes, `bluemap_config`, `dashy`'s `conf.yml` and any other directory where the app writes beside a file Ansible placed; `backup_agent`, whose mounts are already read-only bind mounts; app-written state. Files that name the Caddyfile or the identity file without mounting it stay as they are: the certificate-expiry role, the identity-scoping and cloud-sync scenarios, and the test S3 target, which already mounts its identity file read-only.

## Decision

Implements [ADR 0087 (Ansible-rendered files in containers)](../decisions/0087-delivering-files-ansible-renders-to-a-container/revision-000.md), `approved`; this doc tracks build status only.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Caddyfile | Not started | The Caddy role writes the file under the stack directory and Caddy mounts it read-only; the `caddyfile` volume and its `subpath` mount are gone from the catalog and the compose file; the Caddy scenario reads the file on disk and a changed file restarts Caddy |
| 2 | `step-ca`, OpenBao and Minecraft files | Not started | Each file is mounted read-only from the stack directory and the `scripts`, `config` and `extras` volumes are gone; each service starts healthy on a fresh deploy and reads a changed file after the restart |
| 3 | SeaweedFS identity file | Not started | The file is mounted read-only at mode `0600` with `no_log`, owned by the uid of the image's `seaweed` user, and the process reads it after dropping privileges; the identity-scoping scenario passes |
| 4 | Superseded volumes on running hosts | Not started | Each volume the earlier stages made unnecessary is removed from every host through the cleanup playbook, and no catalog entry, compose file or doc names it |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] No file Ansible renders for a container and the container only reads sits in a volume, except the directories named under "Not in".
- [ ] Every such file is mounted `:ro` from the stack directory, at a path outside every volume.
- [ ] A deploy that changes one restarts the container that mounts it and no other, and the container reads the new content, as [`compose-restart-on-changed-mount.md`](compose-restart-on-changed-mount.md) provides.
- [ ] No backup list or restore path names a volume this project removed.
- [ ] `pre-commit run --all-files` passes.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** any ADR revision beyond the edits [`docs/decisions/README.md#assumptions`](../decisions/README.md#assumptions) permits; the Decision of ADR 0087; any volume an app writes to; the Docker socket mounts.
- **Relevant files and interfaces:** `ansible/roles/compose/tasks/init.yaml` and `deploy.yaml` for the direct deploy path; `ansible/roles/caddy/tasks/main.yaml`, which seeds its volume by hand; `ansible/roles/backup_agent/templates/compose.yaml.j2` for the existing read-only file mounts; `docs/topics/deploy/volumes.md` for what exists now.
- **Required checks:** `pre-commit run --all-files`; the Molecule scenario of every role a stage touches; for stage 2, a fresh deploy of each service.

## Risks

- A bind-mounted file must exist before its container first starts, or Docker creates a directory at that path; each stage checks that the deploy writes the file before it brings the stack up.
- A host keeps a removed volume until the cleanup playbook runs, so stages 1 to 3 leave unused volumes until stage 4.
- A secret file that its process does not own is unreadable there even at `0600`, and the volume it came from may have hidden that by chowning it; stage 3 checks the owner on a running container, not only the mode.

## Open items

- **`tinyauth`'s config and CA bundle.** Both paths are set by environment variables, so they could mount outside `/data`, the one place they would not leave a placeholder in a backed-up volume. Decide after stage 3 whether that is worth a stage.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
