---
id: PROJ-tofu-migration-rehearsal
title: Tofu Migration Rehearsal
type: project
status: not-started
blocked: false
summary: Build the isolated 5XX block and run the first restore.yaml against it.
super_project: tofu-vm-provisioning
track: migration
phase: 1-rehearsal
depends_on:
  - project: PROJ-tofu-vm-provisioning
    reason: needs the VM modules and the inventory generator
---

# Tofu Migration Rehearsal

Migration Stage 1 and 1.5 of the plan in [`vm-provisioning.md`](../vm-provisioning.md): Tofu builds an isolated 5XX block, and the first real `restore.yaml` runs against it. It needs the modules and inventory generator from [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md).

## Scope

The 5XX block (OPNsense plus one Ubuntu VM on VLAN 50) and the first `restore.yaml` run against it. Not in scope: the cutover ([`tofu-migration-cutover.md`](tofu-migration-cutover.md)).

## Decision

No ADR. The design is [`vm-provisioning.md`](../vm-provisioning.md), a topic doc that predates ADRs.

"Migration Stage" is `vm-provisioning.md`'s own numbering for its cutover plan, not this doc's stage numbers — the two are independent sequences that happen to share a word; see [`docs/projects/README.md`](README.md#hierarchy).

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Migration Stage 1 + 1.5 — build the 5XX block, first `restore.yaml` run | Not started | the 5XX block is built by Tofu, isolated from production, and the first `restore.yaml` run against it succeeds |

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
[`fire-drill.md`](../fire-drill.md) for how this doubles as the
restore-path fire drill once OpenTofu is up.

## Acceptance criteria

- [ ] The 5XX block (OPNsense plus one Ubuntu VM on VLAN 50) is built by Tofu and isolated from production.
- [ ] The first `restore.yaml` run against it succeeds, as the restore-path fire drill.
- [ ] The resulting behavior is described in [`docs/vm-provisioning.md`](../vm-provisioning.md) or a new topic doc, not only here.

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
