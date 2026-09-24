---
id: PROJ-tofu-vm-provisioning
title: OpenTofu-Driven Proxmox VM Provisioning
type: project
status: de-risking
blocked: false
summary: Tofu skeleton, Ubuntu and OPNsense modules, and the Tofu-to-Ansible inventory generator.
decision: ADR-0048/0
super_project: tofu-vm-provisioning
track: provisioning
---

# OpenTofu-Driven Proxmox VM Provisioning

Builds the OpenTofu code implementing the design already recorded in
[`docs/vm-provisioning.md`](../vm-provisioning.md) — VMID/VLAN/IP/MAC
scheme, Ubuntu/OPNsense provisioning, and the Tofu↔Ansible boundary —
through the migration cutover that design describes. Real motivation,
not just a design preference: a DHCP dual-lease bug on the current
fleet — see
[`netplan-dhcp-identifier.md`](../netplan-dhcp-identifier.md) — is part
of why this design gives Tofu-provisioned VMs static IPs with no DHCP
at all, rather than carrying the same class of problem forward.

The migration and the OPNsense day-2 work are separate projects in the same initiative: [`tofu-migration-rehearsal.md`](tofu-migration-rehearsal.md), [`tofu-migration-cutover.md`](tofu-migration-cutover.md), and [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md). This one is the code they all need.

## Scope

The OpenTofu project, the Ubuntu and OPNsense-shell modules, and the inventory generator. Not in scope: the migration ([`tofu-migration-rehearsal.md`](tofu-migration-rehearsal.md), [`tofu-migration-cutover.md`](tofu-migration-cutover.md)) and OPNsense Phase 2 ([`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md)). VMIDs 103–105 and 401–403 aren't in any Ansible inventory and are out of scope.

## Decision

Implements [ADR 0048](../decisions/0048-where-tofu-credentials-live/revision-000.md) (where Tofu's own credentials live), still `working`, so this project is `de-risking` until that revision's open assumptions are resolved. The rest of the design is [`docs/vm-provisioning.md`](../vm-provisioning.md), a topic doc that predates ADRs; decisions that come out of this work are lineages.

## Environment (baseline, at project start)

Live `pve` node: 6-core i5-9400, 32GB RAM, NVMe boot SSD (`local` +
`local-lvm`, 1TB) plus a secondary HDD (`backup`, 1TB). This is the
actual `qm list` the VMID scheme in `vm-provisioning.md` was checked
against:

| VMID | Name | Status | Notes |
| :-: | :--- | :--- | :--- |
| 103 | Win10ProKMS | stopped | Template; standalone KMS-activated |
| 104 | Win11Pro | stopped | Template; uses KMS on `services` |
| 105 | Win11ProGPU | stopped | Template |
| 201 | OPNsense | running | Gateway |
| 202 | Tailscale | running | Subnet router, `192.168.20.0/24` |
| 203 | Services | running | Ansible-managed |
| 204 | Play | running | Ansible-managed (Minecraft) |
| 205 | Security | running | Ansible-managed |
| 206 | Storage | running | Ansible-managed; SeaweedFS S3 |
| 401 | Development | running | Runs this project's tooling (Tofu/Ansible) |
| 402 | ZorinPC | stopped | Desktop |
| 403 | Personal | running | GPU passthrough |

VMIDs 103–105/401–403 aren't in any Ansible inventory and are out of
this project's scope. `local` has 37GB free, `local-lvm` 523GB,
`backup` 693GB — noted here since it's what informed the "no storage
placement changes needed" call for the ISO/template content type.

This table is a snapshot, not a tracked value — it will drift once
the [migration rehearsal](tofu-migration-rehearsal.md) starts moving real VMs; don't treat it as current after that.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Tofu project skeleton — provider, state backend, secrets bootstrap | Not started | `tofu init` and `plan` succeed against the `pve` node, with state in the `opentofu-state` bucket and credentials where ADR 0048 decides |
| 2 | `proxmox_ubuntu_vm` module | Not started | a module call provisions an Ubuntu VM matching `vm-provisioning.md`'s VMID/VLAN/IP/MAC scheme |
| 3 | `proxmox_opnsense_vm` module — Phase 1 (VM shell + ISO fetch) | Not started | the module creates the OPNsense VM shell and fetches the ISO; install stays manual |
| 4 | Tofu→Ansible inventory generator | Not started | the generated inventory replaces the hand-written entries, including `tailscale` |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — Tofu project skeleton

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
  state-backend S3 credential):
  a real open decision between three options — see the
  [working decision](../decisions/0048-where-tofu-credentials-live/revision-000.md).
  This stage is blocked on it.
- Install: OpenTofu's official apt-repo installer, on VM 401
  ("Development") once it exists, otherwise wherever the repo's
  driven from today. `bpg/proxmox` needs no separate install — fetched
  by `tofu init`, the same way `ansible-galaxy collection install`
  fetches Ansible's collections.

### Stage 3 — OPNsense Phase 1

VM shell + ISO fetch only, per `vm-provisioning.md`'s OPNsense
section — install and initial config stay manual. Phase 2
([`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md)) is where day-2 config becomes API-driven.

## Acceptance criteria

- [ ] `tofu init` and `plan` succeed against the `pve` node with state in the `opentofu-state` bucket on SeaweedFS.
- [ ] Tofu's credentials live where ADR 0048 decides.
- [ ] The modules provision Ubuntu VMs and the OPNsense VM shell to `vm-provisioning.md`'s VMID/VLAN/IP/MAC scheme.
- [ ] The generated inventory replaces the hand-written entries, including `tailscale`.
- [ ] The resulting behavior is described in [`docs/vm-provisioning.md`](../vm-provisioning.md) or a new topic doc, not only here.

## Open items

- Tofu-only secrets and state-backend credential location (Stage 1) —
  [working decision](../decisions/0048-where-tofu-credentials-live/revision-000.md).
- `checkov` (IaC scanning) for the OpenTofu code once it exists, and
  whether to also move Ansible misconfig scanning onto it at the same
  time instead of keeping Trivy — not scoped yet, not actionable
  before Stage 1 lands — see the
  [working decision](../decisions/0038-iac-misconfiguration-scanning/revision-000.md).
- VM 202 ("Tailscale") is Tofu-unmanaged but no longer wholly
  untracked — Stage 1 of
  [`monitoring-host-isolation.md`](monitoring-host-isolation.md) brought it under
  interim Ansible management as the `network_infra` group (see
  [`network-infra.md`](../network-infra.md)) ahead of and independent
  of this project. It becomes Tofu-managed once this project reaches
  its VMID (Migration Stage 2, [`tofu-migration-cutover.md`](tofu-migration-cutover.md)); Stage 4's inventory
  generator should then supersede — not duplicate alongside —
  `inventory.yaml`'s hand-written `tailscale` entry. It's the
  only Tailscale node in the lab today, already acting as the subnet
  router — no fan-out of per-VM installs to consolidate, and no
  exit-node use case exists. What's left for later is routine: advertise
  new subnets as VLANs 30/40 come online, gated by Tailscale ACLs, and
  apply a public-vs-Tailscale-only exposure policy once a public
  service actually exists. Neither needs its own project.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or named by a successor project.
- [ ] The linked revision is `accepted`, another project still names it, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
