---
id: PROJ-tofu-opnsense-day-2
title: OPNsense Day-2 Config via API
type: project
status: de-risking
blocked: false
summary: Kea, VLAN, and static DNS configured through OPNsense's API.
decision: ADR-0040/0
super_project: tofu-vm-provisioning
track: opnsense
depends_on:
  - project: PROJ-tofu-migration-cutover
    reason: needs the VMID-to-IP mapping fully code-driven
---

# OPNsense Day-2 Config via API

Phase 2 of the OPNsense design in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md): day-2 config (Kea, VLAN, static DNS) becomes API-driven. It needs the VMID→IP mapping fully code-driven, which is the end of [`tofu-migration-cutover.md`](tofu-migration-cutover.md).

## Scope

Kea, VLAN, and static DNS for Tofu-provisioned VMs through OPNsense's own config API. Not in scope: Phase 1 (VM shell and ISO), in [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md).

## Decision

Implements [ADR 0040 (Tofu VM DNS)](../decisions/0040-dns-for-tofu-provisioned-vms/revision-000.md) (DNS for Tofu-provisioned VMs), still `working`, so this project is `de-risking` until that revision's open assumptions are resolved.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | OPNsense Phase 2 — API-driven day-2 config (Kea, VLAN, static DNS) | Not started | Kea, VLAN, and static DNS are configured through OPNsense's API, with Tofu-provisioned VMs' DNS handled per ADR 0040 |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — OPNsense Phase 2

Depends on the VMID→IP mapping being fully code-driven (the rest of this initiative).
Static host overrides for Tofu-provisioned VMs go through OPNsense's
own config API against its BIND plugin's normal record model — not
raw zone-file editing, which the plugin doesn't support (verified
against the plugin's own issue tracker, not assumed). Whether this
stays the design, or Tofu-sourced A records move to a dedicated
internal nameserver instead, is a real open decision — see the
[working decision](../decisions/0040-dns-for-tofu-provisioned-vms/revision-000.md).
This stage is blocked on it too.

## Acceptance criteria

- [ ] Kea, VLAN, and static DNS are configured through OPNsense's API.
- [ ] DNS for Tofu-provisioned VMs works as ADR 0040 decides.
- [ ] The resulting behavior is described in [`docs/topics/infra/vm-provisioning.md`](../topics/infra/vm-provisioning.md) or a new topic doc, not only here.

## Open items

- Internal DNS for Tofu-provisioned VMs (Stage 7) —
  [working decision](../decisions/0040-dns-for-tofu-provisioned-vms/revision-000.md).

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
