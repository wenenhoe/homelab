---
id: PROJ-tofu-skeleton
title: OpenTofu Project Skeleton
type: project
status: building
blocked: false
summary: The OpenTofu provider, the state backend on SeaweedFS and the credentials file, so every other Tofu project has somewhere to start.
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

The smallest Tofu project that runs: the provider, the state backend and the file that holds Tofu's own credentials, as [ADR 0048 (Tofu credentials)](../decisions/0048-where-tofu-credentials-live/revision-000.md) decides. It is its own project because everything else in the initiative needs it and nothing else needs the modules: [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md), [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md) and [`gcp-e2-micro-provisioning.md`](gcp-e2-micro-provisioning.md) all start from it. The design is in [`docs/topics/infra/vm-provisioning.md`](../topics/infra/vm-provisioning.md).

## Scope

The `bpg/proxmox` provider with an API token, the `opentofu-state` bucket and backend, the credentials file and its documented path and mode, and installing OpenTofu on the host that runs it. Not in scope: any VM module or the inventory generator ([`tofu-vm-provisioning.md`](tofu-vm-provisioning.md)), the OPNsense provider ([`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md)), and moving the file to the operator host ([`operator-host-takeover.md`](operator-host-takeover.md)).

## Decision

Implements [ADR 0048 (Tofu credentials)](../decisions/0048-where-tofu-credentials-live/revision-000.md), `approved`: the Proxmox token, the OPNsense API key and the state-backend credential live in a file on the host that runs Tofu, outside the repo and OpenBao. This project is the only one that names the revision, so it sets it `accepted` when it closes.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Provider, state backend and credentials file | Not started | `tofu init` and `plan` succeed against the `pve` node, with state in the `opentofu-state` bucket and credentials read from the file ADR 0048 decides, whose path and mode are documented |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — provider, state backend and credentials file

- `bpg/proxmox` provider, API token auth against the `pve` node.
- State backend: S3-compatible, pointed at SeaweedFS on `storage`
  (`s3.store.lan.<main_domain>`, `:8333` internally — see
  `docker/seaweedfs/compose.yaml.j2`). Bucket name: `opentofu-state`,
  matching the `<component>-<purpose>` pattern `openbao-snapshots`
  already uses (`homelab-backups` is the one exception, since it's
  shared across every host rather than owned by one component).
  SeaweedFS doesn't auto-create buckets
  (`ansible/roles/seaweedfs_bucket`) — creating this one is a one-time
  manual step, not yet Ansible-managed.
- Tofu's own secrets (Proxmox API token, OPNsense API key,
  state-backend S3 credential) are read from a file on the Tofu host,
  outside the repo and OpenBao. The stage documents the file's path,
  mode and contents, and the repo ignores any file of that shape.
- Install: OpenTofu's official apt-repo installer, on the host that runs
  Tofu today (VM 401, "Development", once it exists, otherwise wherever
  the repo's driven from). `bpg/proxmox` needs no separate install —
  fetched by `tofu init`, the same way `ansible-galaxy collection
  install` fetches Ansible's collections.

## Acceptance criteria

- [ ] `tofu init` and `plan` succeed against the `pve` node with state in the `opentofu-state` bucket on SeaweedFS.
- [ ] Tofu's credentials are read from the file ADR 0048 decides, with a documented path and mode, and none is in the repo or in the state.
- [ ] The resulting behavior is described in [`docs/topics/infra/vm-provisioning.md`](../topics/infra/vm-provisioning.md) or a new topic doc, not only here.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** any credential or state file in a commit; any ADR revision beyond the edits [`docs/decisions/README.md#assumptions`](../decisions/README.md#assumptions) permits.

## Open items

- An OpenBao on the Tofu host, seeded by a snapshot pulled from the main instance, would replace the credentials file. It needs a pull counterpart of the snapshot push and a new revision of [ADR 0048](../decisions/0048-where-tofu-credentials-live/revision-000.md); not scoped here.
- `checkov` (IaC scanning) for the OpenTofu code once it exists, and whether to also move Ansible misconfig scanning onto it at the same time instead of keeping Trivy — not scoped yet, not actionable before this stage lands — see the [working decision](../decisions/0038-iac-misconfiguration-scanning/revision-000.md).

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
