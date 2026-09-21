---
id: PROJ-tofu-migration-cutover
title: Tofu Migration Cutover
type: project
status: not-started
blocked: false
summary: Rebuild on the real VMID ranges, cut over, and decommission the old VMs.
super_project: tofu-vm-provisioning
track: migration
phase: 2-cutover
depends_on:
  - project: PROJ-tofu-migration-rehearsal
    reason: cutover happens only once the rehearsal is proven
---

# Tofu Migration Cutover

Migration Stage 2 of the plan in [`vm-provisioning.md`](../vm-provisioning.md): rebuild on the real VMID ranges, cut over, and decommission the old VMs. It follows the proven rehearsal in [`tofu-migration-rehearsal.md`](tofu-migration-rehearsal.md).

## Scope

The rebuild on the real VMID ranges (1XX/2XX/…), the cutover, and decommissioning the old VMs. `storage` stays up throughout.

## Decision

No ADR. The design is [`vm-provisioning.md`](../vm-provisioning.md), a topic doc that predates ADRs.

"Migration Stage" is `vm-provisioning.md`'s own numbering for its cutover plan, not this doc's stage numbers — the two are independent sequences that happen to share a word; see [`docs/projects/README.md`](README.md#hierarchy).

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Migration Stage 2 — cutover to real VMID ranges, decommission old VMs | Not started | the VMs are rebuilt on the real VMID ranges, traffic is cut over, and the old VMs are decommissioned with `storage` up throughout |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — Migration Stage 2

Once Migration Stage 1.5 is proven, rebuild on the real VMID ranges
(1XX/2XX/...), cut over, decommission the old VMs. `storage` stays up
throughout every stage — it holds both the Tofu state backend and the
DR restore target.

## Acceptance criteria

- [ ] Every VM is rebuilt on the real VMID ranges by Tofu.
- [ ] The old VMs are decommissioned.
- [ ] `storage` stayed up throughout.
- [ ] The resulting behavior is described in [`docs/vm-provisioning.md`](../vm-provisioning.md) or a new topic doc, not only here.

## Open items

- Migration Stage 2's exact rebuild sequence isn't scoped beyond
  "rebuild on real VMID ranges, cut over, decommission" — needs its
  own detail once Stage 5 is proven.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
