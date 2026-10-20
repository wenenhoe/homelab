---
id: PROJ-tofu-skeleton
title: OpenTofu Project Skeleton
type: project
status: building
blocked: false
summary: The OpenTofu provider, local state and the credentials file, so every other Tofu project has somewhere to start.
decision: ADR-0048/0
allowed_paths:
  - tofu/**
  - .gitignore
  - README.md
  - docs/topics/infra/vm-provisioning.md
  - docs/decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md
super_project: tofu-vm-provisioning
track: provisioning
---

# OpenTofu Project Skeleton

The smallest Tofu project that runs: the provider, local state and the file that holds Tofu's own credentials, as [ADR 0048 (Tofu credentials)](../decisions/0048-where-tofu-credentials-live/revision-000.md) decides. It is its own project because everything else in the initiative needs it and nothing else needs the modules: [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md), [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md) and [`gcp-e2-micro-provisioning.md`](gcp-e2-micro-provisioning.md) all start from it. The design is in [`docs/topics/infra/vm-provisioning.md`](../topics/infra/vm-provisioning.md).

## Scope

The `bpg/proxmox` provider with an API token, local state kept outside git, the credentials file and its documented path and mode, and installing OpenTofu on the host that runs it. Not in scope: a remote state backend (see Open items), any VM module or the inventory generator ([`tofu-vm-provisioning.md`](tofu-vm-provisioning.md)), the OPNsense provider ([`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md)), and moving the file to the operator host ([`operator-host-takeover.md`](operator-host-takeover.md)).

## Decision

Implements [ADR 0048 (Tofu credentials)](../decisions/0048-where-tofu-credentials-live/revision-000.md), `approved`: the Proxmox token, the OPNsense API key and the state-backend credential live in a file on the host that runs Tofu, outside the repo and OpenBao. Only the Proxmox token exists at this stage; the other two join the file when their consumers are built. This project is the only one that names the revision, so it sets it `accepted` when it closes.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Provider, local state and credentials file | Not started | `tofu init` and `plan` succeed against the `pve` node, with state in a local file outside git and credentials read from the file ADR 0048 decides, whose path and mode are documented |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — provider, local state and credentials file

- `bpg/proxmox` provider, API token auth against the `pve` node.
- State: Tofu's default local backend, a file on the Tofu host. The repo
  ignores state files, and the stage documents where the file lives, its
  mode, and that it is the only copy until a remote backend exists.
- Tofu's own secrets (today the Proxmox API token) are read from a file
  on the Tofu host, outside the repo and OpenBao. The stage documents the
  file's path, mode and contents, and the repo ignores any file of that
  shape.
- Install: OpenTofu's official apt-repo installer, on the host that runs
  Tofu today (VM 401, "Development", once it exists, otherwise wherever
  the repo's driven from). `bpg/proxmox` needs no separate install —
  fetched by `tofu init`, the same way `ansible-galaxy collection
  install` fetches Ansible's collections.

## Acceptance criteria

- [ ] `tofu init` and `plan` succeed against the `pve` node with state in a local file outside git.
- [ ] Tofu's credentials are read from the file ADR 0048 decides, with a documented path and mode, and none is in the repo or in the state.
- [ ] The resulting behavior is described in [`docs/topics/infra/vm-provisioning.md`](../topics/infra/vm-provisioning.md) or a new topic doc, not only here.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** any credential or state file in a commit; any ADR revision beyond the edits [`docs/decisions/README.md#assumptions`](../decisions/README.md#assumptions) permits.

## Open items

- A remote state backend, S3-compatible, in a bucket named `opentofu-state` (the `<component>-<purpose>` pattern), reached by `tofu init -migrate-state` from the local file. It cannot depend on a VM Tofu manages, since Tofu has to be able to rebuild that VM, which rules out the SeaweedFS on `storage` as a first choice. A separate small SeaweedFS instance is the idea; where it runs is not decided. SeaweedFS does not auto-create buckets, and its S3 credential would join the credentials file. Not scoped here; choosing the host is a decision, so it likely becomes an ADR and its own project.
- An OpenBao on the Tofu host, seeded by a snapshot pulled from the main instance, would replace the credentials file. It needs a pull counterpart of the snapshot push and a new revision of [ADR 0048](../decisions/0048-where-tofu-credentials-live/revision-000.md); not scoped here.
- `checkov` (IaC scanning) for the OpenTofu code once it exists, and whether to also move Ansible misconfig scanning onto it at the same time instead of keeping Trivy — not scoped yet, not actionable before this stage lands — see the [working decision](../decisions/0038-iac-misconfiguration-scanning/revision-000.md).

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
