---
id: ADR-0088
revision: 0
type: adr
title: "Where a role-deployed stack's compose file lives"
short: Role-deployed stack compose
solution: "The stack's compose file lives under docker/ like every other app's, the host declares the app in compose_apps, and its own role deploys it through the compose role's tasks as a self-managed app"
summary: "Where the compose file of a stack that its own role deploys lives, how a host declares that it runs the stack, and which mechanisms treat it like any other app."
topic: deployment-platform
status: working
related: [ADR-0004, ADR-0065, ADR-0068, ADR-0087]
---

# 0088. Where a role-deployed stack's compose file lives

## Problem

A stack can reach a host two ways: the `compose` role deploys it from
`docker/<app>/` because the host's `compose_apps` names it, or the stack's own
role renders a compose file from its own templates and runs Compose itself. The
second way keeps the stack out of everything keyed on `docker/` and
`compose_apps`. A stack whose content depends on data derived per host has to
choose one, and the choice decides where its compose file lives, how a host
declares that it runs the stack, and whether the stack is reported, cleaned up
and checked like every other.

## Context

- `backup-agent` is the only stack deployed the second way. Its role renders
  `ansible/roles/backup_agent/templates/compose.yaml.j2` into
  `{{ compose_deploy_dir }}/backup-agent` and runs `docker_compose_v2` itself,
  in Play 8, after every other app's volumes exist. Every other compose file in
  the repository is under `docker/<app>/`, and `bind9`, `caddy` and `openbao`
  are the self-managed apps: listed in `compose_self_managed_apps`, left out of
  `compose_app`'s loop, and deployed by their own roles through the `compose`
  role's `init` and `deploy` tasks for their own `resolved_apps` entry.
- What a stack gets from being in `compose_apps` and `docker/`:
  - `compose/tasks/deploy.yaml` records its result, which the end-of-run
    report reads. An app in `resolved_apps` with no recorded result is
    reported as unfinished; `backup-agent` is not in `resolved_apps` and is
    not reported.
  - Orphan cleanup treats a stack directory that no host's `compose_apps`
    names as removable. `backup-agent` is on `compose_cleanup_exclude` for
    that reason, since cleanup would stop its container.
  - CI decides its app set from `docker/<app>/compose.yaml*`, and a boot-test
    exclusion file names the apps that cannot boot in isolation.
- A host runs the agent exactly when its `backup_plan` is non-empty
  ([ADR 0068 (Backup defaults)](../0068-where-per-app-backup-settings-get-their-defaults/revision-000.md)),
  and `backup_plan` is `resolved_apps | backup_plan(backup_defaults)`. The
  catalog validator already computes which hosts run a backed-up app, from
  plain inventory YAML, to check their SeaweedFS credentials.
- Roles read `resolved_apps` and never `app_catalog`
  ([ADR 0065 (App defaults merge)](../0065-where-app-defaults-and-host-intent-are-merged/revision-000.md)).
  The consumers of `resolved_apps` that look at an app's contents select on
  `routes` being defined (`caddy`, `bind9`, `caddy_cert_expiry`) or read only
  `name` (`deploy_report`). Stale-volume cleanup finds an app's volumes by the
  label `homelab.app=<name>`, and the agent's volumes are other apps' external
  volumes.
- The stack's other files are not all static. The per-app `conf.d` schedules
  come from a loop over `backup_plan`, `.env` and the GPG key carry secrets, and
  `notification-failure.template` is Go template text whose `{{ ... }}` Jinja
  would try to render. A catalog `configs` entry is a fixed `src`, `dest`,
  `mode`, `owner`, `group`, `force` and `no_log`, rendered through `template`,
  with no condition. The Docker API rules file for the proxy sidecar has no
  Jinja delimiters, and the sidecar's compose label carries its hash.
- `compose-syntax-check` skips `.j2` compose files, so a templated compose file
  is checked by the Molecule scenarios that deploy it.

## Decision

- The compose file moves to `docker/backup-agent/compose.yaml.j2` and the proxy
  rules file to `docker/backup-agent/configs/docker-api-rules.cfg`. The sidecar
  keeps mounting the deployed file read-only, as
  [ADR 0087 (Ansible-rendered files in containers)](../0087-delivering-files-ansible-renders-to-a-container/revision-000.md)
  decides for a file the container only reads. Until the `compose` role restarts
  a container whose bind-mounted file changed, the sidecar's label keeps hashing
  that source file; the mount path on the host does not change.
- `app_catalog` gains a `backup-agent` entry with no volumes, routes or backup
  block, and one `configs` entry for the rules file. The rules file is therefore
  deployed to every host that runs the agent, whether or not an app on it stops
  during its backup.
- The host declares the stack: a host lists `backup-agent` in its `compose_apps`
  exactly when its `backup_plan` is non-empty. The catalog validator enforces
  both directions from inventory YAML, as it does for the SeaweedFS credentials.
- `backup-agent` joins `compose_self_managed_apps`. The role keeps Play 8. It
  builds its schedules, renders the files it generates (`conf.d`, `.env`, the
  GPG key, the notification template, the freshness-check script and units),
  then runs the `compose` role's `init` and `deploy` for its own
  `resolved_apps` entry, as `bind9` and `openbao` do. A host whose plan is
  non-empty and which has no entry fails the role; it is never skipped.
- `backup-agent` joins the boot-test exclusion file and leaves
  `compose_cleanup_exclude`. The role's Molecule scenarios take the compose file
  by symlink from `docker/backup-agent/`.

## Alternatives considered

- **Keep the file in the role and document the exception.** The stack stays
  outside the report, needs its own cleanup exclusion, and every later
  role-owned stack adds another exception to the same rule.
- **Move the file to `docker/backup-agent/` and keep the role running Compose.**
  CI would count it as an app while nothing else did: still no report, still an
  exclusion in cleanup, and two code paths that bring a stack up.
- **Derive the entry instead of declaring it.** The role, or the resolver, adds
  `backup-agent` to `resolved_apps` whenever `backup_plan` is non-empty.
  `backup_plan` is computed from `resolved_apps`, so the list would depend on a
  value computed from itself, and ADR 0065's rule that only the resolver reads
  the catalog would need an exception for it.
- **Keep the rules file in the role's `files/` and deploy it conditionally.**
  The one benefit is that hosts without a stop-during-backup app never receive
  it. It costs a stack whose static definition sits in two trees, with the hash
  lookup and its tests pointing outside `docker/`.
- **A `when` key on catalog `configs`.** Changes a schema every app shares, for
  one file whose only cost when unconditional is an unread 0644 file.

## Assumptions

- **Claim:** The compose role renders `docker/backup-agent/compose.yaml.j2` to
  the same bytes the role renders today for every backup host, so the first
  deploy after the change recreates no container.
  **Breaks if wrong:** The cutover restarts the backup agent and its proxy on
  every host, and the proxy as well when the rules file reaches the host with
  different bytes than today's, so its label changes.
  **Checked by:** A spike that renders both for each host's `backup_plan` and
  compares the output and `docker compose config`.
- **Claim:** A catalog entry with no `volumes`, `routes` or `backup` passes the
  catalog validator and every consumer of `resolved_apps`. No existing entry
  lacks all three.
  **Breaks if wrong:** The change needs a validator or consumer fix that is not
  in this decision.
  **Checked by:** Adding the entry in a spike and running the validators and the
  unit tests that read the catalog.

## Consequences

- A host's backup coverage depends on an entry written by hand. A missing entry
  fails the validator in CI and the role at deploy time; it cannot pass quietly.
- The rules file sits on hosts that have no stop-during-backup app. The
  `no_stop_apps` scenario asserts that the proxy service is absent instead of
  the file.
- `backup-agent` appears in the end-of-run report, and orphan cleanup removes
  its stack on a host that drops the entry.
- The compose file's syntax is checked only by the role's Molecule scenarios,
  as it is today.
- The files the role generates stay in the role. Moving the static ones that
  Jinja would not corrupt is a separate decision.
- Topic docs that state where compose files live, how cleanup excludes stacks,
  and which apps CI skips change in the pull requests that change those
  behaviours. [`conventions.md`](../../topics/engineering/conventions.md) states
  today's exception.

## Invariants

- Every stack's compose file is under `docker/<app>/`.
- A host's `compose_apps` names `backup-agent` exactly when its `backup_plan` is
  non-empty.
- An edit to the rules file reaches the running proxy in the next deploy.

## Non-goals

- Moving the generated files, the freshness-check units or the notification
  template out of the role.
- Changing when the agent deploys, what it backs up or how it reaches
  SeaweedFS.
- `cloud-sync` and `openbao-backup`, which have no compose file.

## Validation

The catalog validator's two-way check on `backup-agent`, a unit test for it, the
`backup_agent` Molecule scenarios deploying the symlinked compose file and
asserting the rules file and that an edit to it recreates the proxy, and the
`deploy_report` entry for the agent on every backup host.
