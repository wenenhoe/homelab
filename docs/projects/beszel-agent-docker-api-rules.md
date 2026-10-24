---
id: PROJ-beszel-agent-docker-api-rules
title: "Beszel Agent Docker API Rules"
type: project
status: not-started
blocked: false
summary: "Replace the beszel-agent proxy's CONTAINERS=1 flag with a rules file naming the calls the pinned agent makes, delivered to the host and tried against the proxy image."
super_project: compose-stack-files
track: docker-api
allowed_paths:
  - docker/beszel-agent/**
  - ansible/inventory/group_vars/all/app_catalog.yaml
  - docs/topics/monitoring/beszel.md
  - docs/topics/deploy/adding-an-app.md
  - docs/topics/engineering/molecule-testing.md
---

# Beszel Agent Docker API Rules

Gives the `beszel-agent` proxy the same kind of policy `backup-agent`'s proxy has: a rules file that names each call and refuses the rest, in place of the `CONTAINERS=1` flag. It is staged because how the file reaches the host and how an edit recreates the proxy is not settled, and the call-set check needs a place to run before the file can be trusted.

## Scope

In: a rules file for the proxy beside `docker/beszel-agent/compose.yaml`, mounted read-only over the image's `haproxy.cfg.template`, with `CONTAINERS` and `POST` removed from the service; the way that file reaches the host and the proxy is recreated when it changes; a check that sends each call the agent makes, and each call the rules refuse, through the pinned proxy image in front of a fake socket; the Beszel, app-adding and Molecule topic docs.

Not in: the `backup_agent` proxy and its rules file; the hub; Beszel's version pin; a Renovate manager for the rules file; the proxy's published address (`127.0.0.1:2375` on the host network); changing which calls Beszel makes; the app's name and keys in `ansible/inventory/`, `ansible/ci-inventory/` and the Molecule fixtures, none of which change; `.github/renovate.json5`, whose `docker-socket-proxy` group already moves both proxies' pins together; `tools/ci/provenance/registry.py`, which covers the images and not the rules; `docs/topics/deploy/volumes.md`, which lists the socket by category.

## Decision

None gates this. [ADR 0004 revision 1 (Docker API access)](../decisions/0004-container-access-to-the-docker-api/revision-001.md) is `accepted` and records that `beszel-agent` keeps its flags until a separate change applies a file per consumer; this is that change. If implementing it needs a different Decision, it stops there ([`README.md#stop-conditions`](README.md#stop-conditions)).

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Settle delivery and where the check runs | Not started | This doc names how `docker/beszel-agent/` ships the rules file to the host unchanged, how an edit to it recreates the proxy (Compose does not recreate a container when a bind-mounted file changes, and HAProxy reads the rules only at start), and where the call-set check runs. `allowed_paths` covers every file stages 2 and 3 edit, widened in its own change before it is used. Open items 1 and 3 are closed |
| 2 | The rules file and its check | Not started | The proxy mounts the rules file read-only over the template and sets no flag. Every call in the call set below that the rules admit reaches a fake socket as the same method and target, with and without a query string. Every other call gets a 403 and never arrives: `archive`, `export`, `top`, `events`, `info` and the image calls unless open item 2 admits them, a write verb on any path, and a container id that is not 12 to 64 hex digits. Editing the file recreates the proxy, shown by a changed file giving a new container. The pinned agent image run against the proxy reads the container list and a container's stats, shown by 200s in the proxy's request log |
| 3 | Docs | Not started | `beszel.md` describes the rules file and what the proxy admits, `adding-an-app.md` and `molecule-testing.md` describe the check, and no doc still says the sidecar is scoped by `CONTAINERS=1` |

Stage status is `Not started`, `In progress`, or `Done`.

### Call set at Beszel 0.21.0

Read from the agent's source at the `v0.21.0` tag (`agent/docker.go`, `agent/docker_registry.go`), which is the version the compose file pins. The agent sends paths with no API version prefix. A container id from the hub must match `^[a-fA-F0-9]{12,64}$`; the agent's own stats calls use the first 12 characters of an id.

| Call | Made by | When | Today's flags |
| :--- | :--- | :--- | :--- |
| `GET /containers/json` | `getDockerStats` | Every poll | Admitted |
| `GET /containers/{id}/stats?stream=0&one-shot=1` | `updateContainerStats` | Each listed container, every poll | Admitted |
| `GET /version` | `checkDockerVersion` | At start and after the first list; also the proxy's healthcheck | Admitted |
| `GET /containers/{id}/json` | `getContainerInfo` on a hub request; `getPodmanContainerHealth` on Podman only | On demand | Admitted |
| `GET /containers/{id}/logs?timestamps=1&stdout=1&stderr=1&tail=200` | `getLogs` on a hub request | On demand | Admitted |
| `GET /info` | `GetHostInfo`, which ignores an error | Once, for the host's details | Refused |
| `GET /images/{name}/json` | `inspectImageDigests`, for an image reference not pinned by a digest, unless `DOCKER_IMAGE_CHECK=false` | Background, per image | Refused |

`CONTAINERS=1` with `POST=0` admits every `GET` whose path starts with `/containers`, so today it also admits `archive`, `export`, `top` and the rest, plus `/_ping`, `/version` and `/events`. The agent removes `Config.Env` from the inspect data before it returns it to the hub, but the proxy cannot: an inspect call still delivers the environment to the agent process.

## Acceptance criteria

- [ ] The running `beszel-agent` proxy has the rules file mounted read-only over the template and no `CONTAINERS`, `POST` or other flag switched on, verified on the container.
- [ ] Each call the rules admit gets a 200 and arrives at a fake socket as the same method and target; each other call tried gets a 403 and never arrives. Both run on the pinned proxy image against the deployed file.
- [ ] A change to the rules file recreates the proxy container on the next deploy, verified.
- [ ] The pinned agent image, run against the proxy, gets 200s for the container list and a stats call, shown in the proxy's request log.
- [ ] The call set in this doc is the one the pinned agent makes at the pinned version, re-read from its source at that tag when the pin moves.
- [ ] `pre-commit run --all-files` passes.

## Agent handoff

Stop conditions are in [`README.md#stop-conditions`](README.md#stop-conditions); they apply without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the `backup_agent` role and its scenario; the linked decision's text; which calls Beszel makes. A change to how `ansible/roles/compose/` deploys an app stops the work and goes to the maintainer.
- **Relevant files and interfaces:** `docker/beszel-agent/compose.yaml`; `ansible/roles/backup_agent/files/docker-api-rules.cfg` and `ansible/roles/backup_agent/molecule/default/` for the shape of a rules file, its hash label and its fake-socket check; `ansible/playbooks/ci_boot_test.yaml` and the `compose-boot-test` job, which boot the real compose file in CI.
- **Required checks:** `pre-commit run --all-files` with the hooks that need Docker or network skipped and named; `uv run pytest` from `tools/`; the call-set check on the pinned proxy image; a re-read of the agent's source at the pinned tag.

## Risks

- Beszel's call set moves with its releases. The check proves the rules against the calls listed here, not against a newer agent, so a bump of the agent image can add a call the rules refuse. How the agent reports a refused call differs by call (the host details and image lookups ignore the error), so review a bump against the source at the new tag.
- The check runs the proxy against a fake socket on the test host's kernel; it proves the rules, and the boot test proves the proxy starts, not that the hub shows the same data.

## Open items

1. How `docker/beszel-agent/` ships the file verbatim and how an edit recreates the proxy. An `app_catalog` `configs` entry renders its source through `template`, and a `scripts` entry lands under `scripts/`; neither adds a content label of the kind `backup_agent` renders into its compose template. Whether this needs a change under `ansible/roles/compose/` decides the scope.
2. Whether the rules admit `GET /info` and `GET /images/{name}/json`. Today's flags refuse both, so a file that names only the first five calls changes nothing the hub shows. Admitting them is a change in what the agent can read and is the maintainer's call.
3. Where the call-set check runs. `beszel-agent` has no role or scenario of its own, and the fake socket and checker that `backup_agent` uses live under that role. Sharing them moves files out of a role this project must not change, so that needs its own change first; copying them duplicates a checker.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
