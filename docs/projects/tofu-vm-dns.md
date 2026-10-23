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
---

# DNS for Tofu-Provisioned VMs

The DNS part of the OPNsense Phase 2 design in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md): internal records for Tofu-provisioned VMs. It reads the VMID→IP mapping the inventory generator already publishes, and [`tofu-migration.md`](tofu-migration.md)'s first rebuild waits for it. VLAN interfaces, firewall rules and Kea are [`opnsense-config.md`](opnsense-config.md)'s.

## Scope

Internal DNS records for Tofu-provisioned VMs. Not in scope: Phase 1 (VM shell and ISO), in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md#opnsense), and VLAN interfaces, firewall rules and Kea ([`opnsense-config.md`](opnsense-config.md)).

## Decision

Implements [ADR 0040 (Tofu VM DNS)](../decisions/0040-dns-for-tofu-provisioned-vms/revision-000.md) (DNS for Tofu-provisioned VMs), still `working`, so this project is `de-risking` until that revision's open assumptions are resolved.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Settle the assumptions in ADR 0040 | In progress | Each assumption is resolved and folded into the revision's Context, and the revision can be `approved` |
| 2 | Records for Tofu-provisioned VMs | Not started | DNS for Tofu-provisioned VMs works as ADR 0040 decides |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 2 — records

Reads the VMID→IP mapping from the inventory generator
([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#tofu--ansible-handoff)),
and finishes before [`tofu-migration.md`](tofu-migration.md)'s first rebuild.
A second BIND9 on `security` holds the A records, fed by the inventory
generator, and the gateway's Unbound forwards that zone and `services`'
zone to their servers ([ADR 0089 (OPNsense configuration)](../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md)
owns the forwards).

The inventory generator checks a host name with `^[a-z][a-z0-9-]*$`, which
admits a trailing hyphen and a name over 63 characters. Neither is a DNS
label, and the same name becomes the record's owner name, so this stage
tightens that check.

## Acceptance criteria

- [ ] DNS for Tofu-provisioned VMs works as ADR 0040 decides.
- [ ] The resulting behavior is described in [`docs/topics/infra/vm-provisioning.md`](../topics/infra/vm-provisioning.md) or a new topic doc, not only here.

## Open items

None beyond the assumptions recorded in the decision.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
