---
id: ADR-0121
revision: 0
type: adr
title: "Knowing what components the lab is made of"
short: Component inventory
solution: "The repo's Ansible declarations are the inventory: hosts in inventory.yaml, apps in each host's compose_apps, and each app's host-independent facts once in app_catalog"
summary: "Where the list of the hosts and apps that make up the lab is kept, what it records about each, and what keeps it complete."
topic: deployment-platform
status: accepted
related: [ADR-0001, ADR-0065, ADR-0088, ADR-0100]
---

# 0121. Knowing what components the lab is made of

## Problem

Someone has to be able to answer which hosts the lab has, which apps each one
runs and what each app needs, without logging in to a host. The same facts
drive what is deployed and what is generated from it, so a second copy that can
disagree with the first answers neither.

## Context

This record was written after the structure it describes was in use.

- The first host lists, in June 2026, were `compose_apps` entries in each
  host's `host_vars`. An app's own facts sat inline in those entries or in
  shared lists and maps beside them (`compose_has_env`, `docker_upstreams`,
  `docker_exclude_sso`).
- A test host meant repeating app definitions, and the copies had drifted: its
  `dashy` entry lacked the directory and the config template that the same
  app's entry on the `services` host had. The `diun` config block was written
  out on several hosts.
- In July 2026 the facts that do not vary by host moved into one entry per app,
  `app_registry`, leaving each host file to say which apps it runs and under
  which hostnames. Being able to say what runs where was a motive. In August
  the registry got its own file.
- In September 2026
  [ADR 0065 (App defaults merge)](../0065-where-app-defaults-and-host-intent-are-merged/revision-000.md)
  renamed it `app_catalog` and fixed how it is merged with a host's entries.
- Caddy's configuration was generated from the host lists before the registry
  existed. The registry gave it, and the other readers of an app's facts, one
  place to read them from.
- The tool that deploys the lab is Ansible
  ([ADR 0001 (Host config from repo)](../0001-host-configuration-reproducible-from-repo/revision-000.md)),
  so a declaration it reads cannot be left behind by a deploy.

## Decision

The inventory is the repo's own Ansible declarations. There is no separate
inventory document or service.

- A **component** is a host that `ansible/inventory/inventory.yaml` declares,
  or an app that a managed host lists in `compose_apps`.
- Which hosts exist, and the groups each belongs to, is `inventory.yaml`. What
  a host runs, and what differs on that host, is its `host_vars`.
- What does not vary by host is written once, in the app's `app_catalog` entry:
  its volumes, configs, routes, backup scope, recovery tier and service record
  ([ADR 0100 (Recording a system's integration)](../0100-recording-how-a-system-is-integrated/revision-001.md)).
  The fields are described in
  [`adding-an-app.md`](../../topics/deploy/adding-an-app.md#2-register-it-in-app_catalog)
  and [`host-vars.md`](../../topics/deploy/host-vars.md#compose_apps).
- Every app a managed host lists has a catalog entry. A repo check fails one
  that does not, on every pull request. That is the review of the inventory;
  there is no separate periodic one.
- A systemd unit or container that a role installs without a `compose_apps`
  entry is part of that host's configuration, not a component of its own.

## Alternatives considered

- **Leave each app's facts with the hosts that run it.** The state before the
  registry: adding a host repeats the definitions, and the copies drift.
- **A role per app.** An app's facts would sit in its own role, so saying what
  runs where means reading every role. Roles of their own stay for the apps
  that need handling the shared one cannot give.
- **A metadata file beside each app's compose file.** Rejected in July 2026
  because it moves `docker/<app>/` away from plain Docker. That argument has
  weakened where a compose file is a template.
- **NetBox or another CMDB.** Assessed when this record was written: a second
  source of truth to keep in step with what is deployed, and one more service
  to run.
- **Discovery from the running hosts.** Assessed when this record was written:
  it shows what is running, not what should be.

## Consequences

- Adding a component is the change that deploys it, so the inventory is not a
  separate chore.
- The inventory states what is declared. It is not built from what is observed
  on a host.
- A stack that a role deploys from its own templates, without a `compose_apps`
  entry, is absent from the app list. The backup agent is one;
  [ADR 0088 (Role-deployed stack compose)](../0088-where-a-role-deployed-stack-compose-file-lives/revision-000.md)
  proposes declaring it like any other app.

## Invariants

- Every app a managed host lists in `compose_apps` has an `app_catalog` entry.
- Every catalog entry names a service record.
- An app's host-independent facts are defined in its catalog entry; a host's
  entry holds what that host adds or overrides.

## Non-goals

- Comparing what runs on a host with what the repo declares.
- Listing what `inventory.yaml` and `compose_apps` do not: VM and network
  definitions held elsewhere in the repo, packages on a host, and the units and
  containers a role installs.
- Listing container images, which are collected from the files that pin them
  ([ADR 0108 (Images a deploy runs)](../0108-which-images-a-deploy-runs-and-where-they-come-from/revision-000.md)).
- Requiring every catalog entry to be run by some host.

## Validation

`ci.gates.app_catalog_rules`, run by the `check-app-catalog` hook, fails a
listed app with no catalog entry and a repeated app name. The docs drift check
fails a catalog entry whose service record is missing or lacks a section.

## Reconsideration triggers

- Something the repo does not declare is found running on a host it manages.
- A kind of component has to be listed that Ansible does not declare.
- The inventory needs a reader that cannot work from the repo.
