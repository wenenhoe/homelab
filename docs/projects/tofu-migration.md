---
id: PROJ-tofu-migration
title: Tofu Migration
type: project
status: not-started
blocked: false
summary: Build the isolated 5XX block and run the first restore.yaml against it, then rebuild on the real VMID ranges, cut over, and decommission the old VMs.
super_project: tofu-vm-provisioning
track: migration
depends_on:
  - project: PROJ-tofu-vm-provisioning
    reason: needs the VM modules and the inventory generator
---

# Tofu Migration

Migration Stages 1, 1.5 and 2 of the plan in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md): Tofu builds an isolated 5XX block, the first real `restore.yaml` runs against it, and once that is proven the VMs are rebuilt on the real VMID ranges, traffic is cut over and the old VMs are decommissioned. It needs the modules and inventory generator from [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md).

## Scope

The 5XX block (OPNsense plus one Ubuntu VM on VLAN 50), the first `restore.yaml` run against it, the rebuild on the real VMID ranges (1XX/2XX/…), the cutover, and decommissioning the old VMs. `storage` stays up throughout. Not in scope: OPNsense day-2 configuration ([`opnsense-config.md`](opnsense-config.md)).

## Decision

No ADR. The design is [`vm-provisioning.md`](../topics/infra/vm-provisioning.md), a topic doc that predates ADRs.

"Migration Stage" is `vm-provisioning.md`'s own numbering for its cutover plan. This doc's Stage 1 is Migration Stages 1 and 1.5, and its Stage 2 is Migration Stage 2.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Migration Stage 1 + 1.5 — build the 5XX block, first `restore.yaml` run | Not started | the 5XX block is built by Tofu, isolated from production, and the first `restore.yaml` run against it succeeds |
| 2 | Migration Stage 2 — cutover to real VMID ranges, decommission old VMs | Not started | the VMs are rebuilt on the real VMID ranges, traffic is cut over, and the old VMs are decommissioned with `storage` up throughout |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — Migration Stage 1 + 1.5

The current 2XX hosts are live and can't be edited in place, and
resources on `pve` are tight enough that downsizing during the move is
part of the plan — migration happens in stages rather than a single
cutover.

**Migration Stage 1** — Tofu provisions a new OPNsense + one Ubuntu VM
on the `5XX` block (VLAN 50), fully isolated from production. Its WAN
NIC plugs into the same VLAN-aware trunk bridge as everything else,
tagged into VLAN 20 — an ordinary DHCP client of the *current*
OPNsense's LAN, not the physical WAN bridge. This lets it reach
`storage` (still live, same VLAN) and the internet (NATed through the
current OPNsense) with zero firewall/routing changes on production.

**Migration Stage 1.5** — first real run of `restore.yaml` against the
Stage 1 VM(s): validates disaster recovery and rehearses the actual
cutover mechanics at the same time. See
[`fire-drill.md`](../topics/disaster-recovery/fire-drill.md) for how this doubles as the
restore-path fire drill once OpenTofu is up.

### Stage 2 — Migration Stage 2

Once Migration Stage 1.5 is proven, rebuild on the real VMID ranges
(1XX/2XX/...), cut over, decommission the old VMs. `storage` stays up
throughout every stage — it is the DR restore target.

## Acceptance criteria

- [ ] The 5XX block (OPNsense plus one Ubuntu VM on VLAN 50) is built by Tofu and isolated from production.
- [ ] The first `restore.yaml` run against it succeeds, as the restore-path fire drill.
- [ ] Every VM is rebuilt on the real VMID ranges by Tofu.
- [ ] The old VMs are decommissioned.
- [ ] `storage` stayed up throughout.
- [ ] The resulting behavior is described in [`docs/topics/infra/vm-provisioning.md`](../topics/infra/vm-provisioning.md) or a new topic doc, not only here.

## Open items

- Migration Stage 2's exact rebuild sequence isn't scoped beyond
  "rebuild on real VMID ranges, cut over, decommission" — needs its
  own detail once Stage 1 is proven.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
