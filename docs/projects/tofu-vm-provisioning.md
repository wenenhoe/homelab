---
id: PROJ-tofu-vm-provisioning
title: OpenTofu-Driven Proxmox VM Provisioning
type: project
status: building
blocked: false
summary: Ubuntu and OPNsense modules, and the Tofu-to-Ansible inventory generator, built on the Tofu skeleton.
super_project: tofu-vm-provisioning
track: provisioning
---

# OpenTofu-Driven Proxmox VM Provisioning

Builds the OpenTofu code implementing the design already recorded in
[`docs/topics/infra/vm-provisioning.md`](../topics/infra/vm-provisioning.md) — VMID/VLAN/IP/MAC
scheme, Ubuntu/OPNsense provisioning, and the Tofu↔Ansible boundary —
through the migration cutover that design describes. Real motivation,
not just a design preference: a DHCP dual-lease bug on the current
fleet — see
[`netplan-dhcp-identifier.md`](../topics/infra/netplan-dhcp-identifier.md) — is part
of why this design gives Tofu-provisioned VMs static IPs with no DHCP
at all, rather than carrying the same class of problem forward.

The migration, the OPNsense day-2 work and DNS for the VMs are separate projects in the same initiative: [`tofu-migration.md`](tofu-migration.md), [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md) and [`tofu-vm-dns.md`](tofu-vm-dns.md). This one is the modules and inventory generator they all need.

## Scope

The Ubuntu and OPNsense-shell modules and the inventory generator, on the root module in `tofu/` ([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#tofu-project)). Not in scope: the migration ([`tofu-migration.md`](tofu-migration.md)), OPNsense Phase 2 ([`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md)) and DNS for the VMs ([`tofu-vm-dns.md`](tofu-vm-dns.md)). VMIDs 103–105 and 401–403 aren't in any Ansible inventory and are out of scope.

## Decision

No decision of its own. Tofu's credentials are [ADR 0048 (Tofu credentials)](../decisions/0048-where-tofu-credentials-live/revision-000.md)'s, carried out as [`vm-provisioning.md`](../topics/infra/vm-provisioning.md#state-backend--secrets) describes. The design is [`docs/topics/infra/vm-provisioning.md`](../topics/infra/vm-provisioning.md), a topic doc that predates ADRs; decisions that come out of this work are lineages.

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
the [migration](tofu-migration.md) starts moving real VMs; don't treat it as current after that.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | `proxmox_ubuntu_vm` module | Done | a module call provisions an Ubuntu VM matching `vm-provisioning.md`'s VMID/VLAN/IP/MAC scheme |
| 2 | `proxmox_opnsense_vm` module — Phase 1 (VM shell + ISO fetch) | Not started | the module creates the OPNsense VM shell and fetches the ISO; install stays manual |
| 3 | Tofu→Ansible inventory generator | Not started | the generated inventory replaces the hand-written entries, including `tailscale` |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 2 — OPNsense Phase 1

VM shell + ISO fetch only, per `vm-provisioning.md`'s OPNsense
section — install and initial config stay manual. Phase 2
([`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md)) is where day-2 config becomes API-driven.

## Acceptance criteria

- [ ] The modules provision Ubuntu VMs and the OPNsense VM shell to `vm-provisioning.md`'s VMID/VLAN/IP/MAC scheme.
- [ ] The generated inventory replaces the hand-written entries, including `tailscale`.
- [ ] The resulting behavior is described in [`docs/topics/infra/vm-provisioning.md`](../topics/infra/vm-provisioning.md) or a new topic doc, not only here.

## Open items

- VM 202 ("Tailscale") is Tofu-unmanaged but no longer wholly
  untracked — Stage 1 of
  [`monitoring-host-isolation.md`](monitoring-host-isolation.md) brought it under
  interim Ansible management as the `network_infra` group (see
  [`network-infra.md`](../topics/infra/network-infra.md)) ahead of and independent
  of this project. It becomes Tofu-managed once this project reaches
  its VMID (Migration Stage 2, [`tofu-migration.md`](tofu-migration.md)); Stage 3's inventory
  generator should then supersede — not duplicate alongside —
  `inventory.yaml`'s hand-written `tailscale` entry. It's the
  only Tailscale node in the lab today, already acting as the subnet
  router — no fan-out of per-VM installs to consolidate, and no
  exit-node use case exists. What's left for later is routine: advertise
  new subnets as VLANs 30/40 come online, gated by Tailscale ACLs, and
  apply a public-vs-Tailscale-only exposure policy once a public
  service actually exists. Neither needs its own project.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
