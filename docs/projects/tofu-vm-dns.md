---
id: PROJ-tofu-vm-dns
title: DNS for Tofu-Provisioned VMs
type: project
status: de-risking
blocked: false
summary: Internal DNS records for Tofu-provisioned VMs, as ADR 0040 decides.
decision: ADR-0040/0
super_project: tofu-vm-provisioning
track: dns
depends_on:
  - project: PROJ-tofu-migration
    reason: needs the VMID-to-IP mapping fully code-driven
---

# DNS for Tofu-Provisioned VMs

The DNS part of the OPNsense Phase 2 design in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md): internal records for Tofu-provisioned VMs. It needs the VMID→IP mapping fully code-driven, which is the end of [`tofu-migration.md`](tofu-migration.md). VLAN interfaces, firewall rules and Kea are [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md)'s.

## Scope

Internal DNS records for Tofu-provisioned VMs. Not in scope: Phase 1 (VM shell and ISO), in [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md), and VLAN interfaces, firewall rules and Kea ([`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md)).

## Decision

Implements [ADR 0040 (Tofu VM DNS)](../decisions/0040-dns-for-tofu-provisioned-vms/revision-000.md) (DNS for Tofu-provisioned VMs), still `working`, so this project is `de-risking` until that revision's open assumptions are resolved.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Settle the assumptions in ADR 0040 | Not started | Each assumption is resolved and folded into the revision's Context, and the revision can be `approved` |
| 2 | Records for Tofu-provisioned VMs | Not started | DNS for Tofu-provisioned VMs works as ADR 0040 decides |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 2 — records

Depends on the VMID→IP mapping being fully code-driven ([`tofu-migration.md`](tofu-migration.md)).
Static host overrides for Tofu-provisioned VMs go through OPNsense's
own config API against its BIND plugin's normal record model — not
raw zone-file editing, which the plugin doesn't support (verified
against the plugin's own issue tracker, not assumed). Whether this
stays the design, or Tofu-sourced A records move to a dedicated
internal nameserver instead, is a real open decision — see the
[working decision](../decisions/0040-dns-for-tofu-provisioned-vms/revision-000.md).
This stage is blocked on it.

## Acceptance criteria

- [ ] DNS for Tofu-provisioned VMs works as ADR 0040 decides.
- [ ] The resulting behavior is described in [`docs/topics/infra/vm-provisioning.md`](../topics/infra/vm-provisioning.md) or a new topic doc, not only here.

## Open items

None beyond the assumptions recorded in the decision.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
