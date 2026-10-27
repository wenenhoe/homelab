---
id: PROJ-tofu-vm-dns
title: DNS for Tofu-Provisioned VMs
type: project
status: not-started
blocked: false
summary: Internal DNS records for Tofu-provisioned VMs, as ADR 0040 decides.
decision: ADR-0040/0
super_project: tofu-vm-provisioning
track: dns
---

# DNS for Tofu-Provisioned VMs

The DNS part of the OPNsense Phase 2 design in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md): internal records for Tofu-provisioned VMs. It reads the VMID→IP mapping the inventory generator already publishes, and [`tofu-migration.md`](tofu-migration.md)'s first rebuild waits for it. VLAN interfaces, firewall rules and Kea are [`opnsense-config.md`](opnsense-config.md)'s.

## Scope

Internal DNS records for Tofu-provisioned VMs, and the live exercise that shows the names survive the loss of either server. Not in scope: the host zone and the secondary, which are in place ([`bind9.md`](../topics/services/bind9.md)), Phase 1 (VM shell and ISO), in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md#opnsense), and VLAN interfaces, firewall rules and Kea ([`opnsense-config.md`](opnsense-config.md)).

## Decision

Implements [ADR 0040 (Tofu VM DNS)](../decisions/0040-dns-for-tofu-provisioned-vms/revision-000.md), `approved`. This project is the last to name it.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Records for Tofu-provisioned VMs | Not started | The `bind9` role builds a record for each generated host in the host zone, and the zone on both servers holds them |
| 2 | Lose each server live | Not started | With the `services` server stopped, a host name and a service name resolve from each VLAN through the secondary, and resolve from `services` again once it is back; the same with `storage` stopped, through `services` |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — records

Reads the VMID→IP mapping from the inventory generator
([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#tofu--ansible-handoff)),
and finishes before [`tofu-migration.md`](tofu-migration.md)'s first rebuild.

The inventory generator checks a host name with `^[a-z][a-z0-9-]*$`, which
admits a trailing hyphen and a name over 63 characters. Neither is a DNS
label, and the same name becomes the record's owner name, so this stage
tightens that check.

## Acceptance criteria

- [ ] DNS for Tofu-provisioned VMs works as ADR 0040 decides.
- [ ] A probe from each VLAN resolves a name in the host zone and one in a service zone through the gateway, with either server stopped.
- [ ] The resulting behavior is described in [`docs/topics/infra/vm-provisioning.md`](../topics/infra/vm-provisioning.md) or a new topic doc, not only here.

## Open items

None beyond the assumption recorded in the decision.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
