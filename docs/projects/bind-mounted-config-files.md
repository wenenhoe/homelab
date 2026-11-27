---
id: PROJ-bind-mounted-config-files
title: "Bind-Mounted Config Files"
type: project
status: not-started
blocked: false
summary: "Restart a container when a file bind-mounted into it changes, then mount files Ansible renders read-only from the stack directory, so a config file no longer needs a volume of its own."
decision: ADR-0087/0
super_project: compose-stack-files
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
  - ansible/filter_plugins/compose_mounts.py
  - ansible/tests/test_compose_mounts.py
  - ansible/tests/test_resolved_apps_consumers.py
  - docs/topics/deploy/**
  - docs/topics/services/caddy.md
  - docs/topics/services/step-ca.md
  - docs/topics/security/openbao/deployment.md
  - docs/topics/disaster-recovery/backup.md
  - docs/topics/testing/molecule-testing.md
---

# Bind-Mounted Config Files

Moves the files Ansible renders for a container out of volumes and into read-only bind mounts, following [ADR 0087 (Ansible-rendered files in containers)](../decisions/0087-delivering-files-ansible-renders-to-a-container/revision-000.md). The first stage is the mechanism an app's file needs before it can move: a changed mounted file restarts its container. Each app's move then ships and verifies on its own.

## Scope

In: the `compose` role's detection of a changed file that a service mounts from its stack directory, with its filter plugin, unit tests and Molecule scenario, and the rule stated in `docs/topics/deploy/volumes.md`; the Caddyfile; `step-ca`'s `entrypoint.sh`; OpenBao's `openbao.hcl`; Minecraft's `modrinth-mods.txt`; SeaweedFS's `s3-identity.json`; removing the volumes those files no longer need, from the catalog, the compose files and running hosts.

Not in: `bind9`'s config, the `certs` volumes, `bluemap_config`, `dashy`'s `conf.yml` and any other directory where the app writes beside a file Ansible placed; `backup_agent`, whose mounts are already read-only bind mounts; app-written state. Files that name the Caddyfile or the identity file without mounting it stay as they are: the certificate-expiry role, the identity-scoping and cloud-sync scenarios, and the test S3 target, which already mounts its identity file read-only.

## Decision

Implements [ADR 0087 (Ansible-rendered files in containers)](../decisions/0087-delivering-files-ansible-renders-to-a-container/revision-000.md), `approved`; this doc tracks build status only.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Restart on a changed bind-mounted file | Not started | A changed file that a service mounts read-only from its stack directory recreates that service in the same run and no other, also on the run after one that failed between writing the file and deploying; a `compose` Molecule scenario changes a mounted direct config and a mounted direct script, asserts the container reads the new content, covers the failed run, and shows that a second run changes nothing; `ansible/tests/test_compose_mounts.py` covers the mount parsing; `volumes.md` states the rule and what stays a volume |
| 2 | Caddyfile | Not started | The Caddy role writes the file under the stack directory and Caddy mounts it read-only; the `caddyfile` volume and its `subpath` mount are gone from the catalog and the compose file; the Caddy scenario reads the file on disk and a changed file restarts Caddy |
| 3 | `step-ca`, OpenBao and Minecraft files | Not started | Each file is mounted read-only from the stack directory and the `scripts`, `config` and `extras` volumes are gone; each service starts healthy on a fresh deploy and reads a changed file after the restart |
| 4 | SeaweedFS identity file | Not started | The file is mounted read-only at mode `0600` with `no_log`, owned by the uid of the image's `seaweed` user, and the process reads it after dropping privileges; the identity-scoping scenario passes |
| 5 | Superseded volumes on running hosts | Not started | Each volume the earlier stages made unnecessary is removed from every host through the cleanup playbook, and no catalog entry, compose file or doc names it |

Stage status is `Not started`, `In progress`, or `Done`.

### How stage 1 picks up a change

The `compose` role meets the ADR's "restarts the container" by having Compose recreate it:

- The role's deploy tasks, before they bring the stack up and under every tag they run with, write `compose.override.yaml` in the stack directory. It gives each service that mounts a file or directory read-only from the stack directory a `homelab.mounted-files-sha256` label: a checksum of that content as it is on the host.
- The mounts are read from the deployed `compose.yaml`, in short and long syntax, by `ansible/filter_plugins/compose_mounts.py`. Named volumes, the Docker socket and other host paths are not counted.
- It covers whatever wrote the file before the deploy tasks ran, a role's own template included, not only catalog configs and scripts.
- An app with no such mount gets no override file, and one left from before is removed.
- Nothing is driven by a task's `changed` result. Volume-seeded files keep the `compose_app_extra_changed` restart.

Compose reads the override from the project directory without being named, since the role passes no file list. A changed label recreates only the service that carries it. A running container keeps the old content of a replaced single file until then.

## Acceptance criteria

- [ ] No file Ansible renders for a container and the container only reads sits in a volume, except the directories named under "Not in".
- [ ] Every such file is mounted `:ro` from the stack directory, at a path outside every volume.
- [ ] A deploy that changes one recreates the container that mounts it and no other, and the container reads the new content, as stage 1 provides.
- [ ] No backup list or restore path names a volume this project removed.
- [ ] `pre-commit run --all-files` passes.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **One stage at a time:** work the first stage that is not `Done`, deliver it, and stop.
- **Must not change:** any ADR revision beyond the edits [`docs/decisions/README.md#assumptions`](../decisions/README.md#assumptions) permits; the Decision of ADR 0087; any volume an app writes to; the Docker socket mounts.
- **Relevant files and interfaces:** `ansible/roles/compose/tasks/init.yaml` and `deploy.yaml` for the direct deploy path and the stack bring-up, which `caddy`, `bind9` and `openbao` call directly; `ansible/filter_plugins/app_deploy_plan.py` and its test for the shape of a filter; `ansible/roles/caddy/tasks/main.yaml`, which seeds its volume by hand; `ansible/roles/backup_agent/templates/compose.yaml.j2` for the existing read-only file mounts; `docs/topics/deploy/volumes.md` for what exists now.
- **Required checks:** `pre-commit run --all-files`; `pytest ansible/tests/ tools/tests/`; the Molecule scenario of every role a stage touches; for stage 3, a fresh deploy of each service.

## Risks

- A role that restarts its service on its own change, as `caddy` does for the Caddyfile, would restart it twice once the file is a mount; the stage that moves the file drops that restart.
- A label can be read by anything with read access to the Docker API. A checksum of a secret file gives nothing away only while every secret in it is a generated random value, as the keys in `s3-identity.json` are. A secret file holding a value a person chose stops the work.
- A bind-mounted file must exist before its container first starts, or Docker creates a directory at that path; each stage checks that the deploy writes the file before it brings the stack up.
- A host keeps a removed volume until the cleanup playbook runs, so stages 2 to 4 leave unused volumes until stage 5.
- A secret file that its process does not own is unreadable there even at `0600`, and the volume it came from may have hidden that by chowning it; stage 4 checks the owner on a running container, not only the mode.

## Open items

- **`tinyauth`'s config and CA bundle.** Both paths are set by environment variables, so they could mount outside `/data`, the one place they would not leave a placeholder in a backed-up volume. Decide after stage 4 whether that is worth a stage.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
