---
id: PROJ-internal-dns-consolidation
title: Internal DNS on services, with a secondary
type: project
status: de-risking
blocked: false
summary: Serve the host zone from services with a static record for every host, retire the gateway's BIND9 zone and dynamic DNS, and add a secondary on storage that the gateway's Unbound forwards to.
decision: ADR-0040/0
super_project: tofu-vm-provisioning
track: dns
allowed_paths:
  - ansible/inventory/**
  - ansible/ci-inventory/**
  - ansible/playbooks/**
  - ansible/roles/**
  - docker/**
  - tools/utils/repo.py
  - tools/ci/fixtures/file_cache_catalog.py
  - tools/openbao_utils/client.py
  - docs/topics/**
  - docs/architecture/reverse-proxy-and-dns.md
---

# Internal DNS on services, with a secondary

The part of [ADR 0040 (Tofu VM DNS)](../decisions/0040-dns-for-tofu-provisioned-vms/revision-000.md) that does not depend on Tofu: `services` serves the host zone, the gateway stops being a source of names, and a second server keeps the names up. It is its own project because [`tofu-vm-dns.md`](tofu-vm-dns.md) cannot start its records until the zone and both servers exist, and a live loss of `services` is exercised there.

## Scope

The renames `ddns_domain` to `host_domain`, `lab_domain` to `lan_domain` and `dns_ddns_target` to `host_fqdn`, across the inventory, roles, tests and docs. The host zone on `services`, with a static record for every host the lab has today, the Proxmox node and the gateway. Retiring the live gateway's BIND9 zone and dynamic DNS by hand, since its configuration stays hand-built until [`opnsense-config.md`](opnsense-config.md) rebuilds it. A secondary on `storage` with a TSIG key, and the second forward address on the gateway. Not in scope: records built from the inventory generator and the live failover exercise ([`tofu-vm-dns.md`](tofu-vm-dns.md)), names for DHCP clients, and the gateway's rebuild.

## Decision

Implements [ADR 0040 (Tofu VM DNS)](../decisions/0040-dns-for-tofu-provisioned-vms/revision-000.md), still `working`, so this project is `de-risking` until its open assumption is resolved. [`tofu-vm-dns.md`](tofu-vm-dns.md) names the same revision and is the last to close, so it accepts it.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Settle the failover assumption in ADR 0040 | Not started | A scratch gateway with two forward addresses for a zone answers a host name, a service name and a CNAME that crosses the zones with the first server stopped, and the revision can be `approved` |
| 2 | Host zone on `services` | Not started | `services` serves the host zone with a static record for every current host, the node and the gateway; every service CNAME points at `host_fqdn`; the renames are done and no old name remains in the tree |
| 3 | Retire the gateway's names | Not started | The live gateway runs no BIND9 zone and no dynamic DNS registration, and every host still resolves from each VLAN |
| 4 | Secondary on `storage` | Not started | `storage` serves both zones from `services` by TSIG-authenticated transfer, picks up a change to the host zone, and the gateway forwards both zones to both servers |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] `services` serves the host zone and the service zones, and no record is registered by the gateway.
- [ ] `storage` serves both zones as a secondary, and a transfer is refused without the key.
- [ ] A name in each zone resolves from every VLAN with either server stopped.
- [ ] The resulting behavior is described in [`bind9.md`](../topics/services/bind9.md) and [`reverse-proxy-and-dns.md`](../architecture/reverse-proxy-and-dns.md), not only here.

## Risks

- The live gateway's configuration is hand-built until its rebuild, so Stages 3 and 4 change it by hand and the change is drift until [`opnsense-config.md`](opnsense-config.md) writes it in code.
- Every current host's address is a DHCP reservation on the live gateway, and Stage 2 repeats each one in a static record. A reservation changed by hand makes its record wrong until that host is rebuilt.

## Open items

None beyond the assumption recorded in the decision.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
