---
id: ADR-0040
revision: 0
type: adr
title: DNS for Tofu-provisioned VMs
short: Tofu VM DNS
solution: A second, dedicated BIND9 on security, fed by the Tofu-to-Ansible inventory generator, with the gateway forwarding each zone to its server
summary: How Tofu-provisioned VMs get internal A records when their IPs are fixed at provision time.
topic: deployment-platform
status: working
related: [ADR-0089]
---

# 0040. DNS for Tofu-provisioned VMs

## Problem

Tofu gives every VM it provisions a fixed address, and those VMs need
internal A records. The records must come from Tofu's data, survive a
rebuild of the gateway, and resolve from every VLAN alongside the zones
that already exist.

## Context

- `services`' BIND9 is the lab's authoritative internal nameserver. It
  aggregates every app host's `dns_zones` from `host_vars` and
  generates CNAMEs for anything with a `caddy` route
  ([`bind9.md`](../../topics/services/bind9.md)). Its `bind9` role also
  supports static `extra_records` per zone, rendered by comparing
  candidate content with live content, serial stripped, and reloading
  only on a real change. Nothing in it needs a dynamic update.
- Tofu-provisioned VMs have static addresses from cloud-init, so no DHCP
  lease and no dynamic DNS is involved in their names. The Tofu to
  Ansible inventory generator reads the root module's `ansible_hosts`
  output, which holds each host's address and login user. The generated
  inventory gives every such host a name (its inventory host name) and an
  address (`ansible_host`), which is all an A record needs, so the
  generator's output keys stay as they are.
- The `bind9` role renders a record only from a zone's `extra_records` in
  an app host's `host_vars`, or as a CNAME for a `caddy` route. The
  second instance therefore adds a step that builds A records from the
  generated hosts; it does not take its records from `host_vars`.
- [ADR 0089 (OPNsense configuration)](../0089-how-the-opnsense-gateway-is-configured/revision-000.md)
  drops dynamic DNS and the BIND plugin from the gateway. Its Unbound
  recurses directly and can forward a named zone to a given server and
  port.

Feeding Tofu's data into the `services` role would tie two independently
changing data sources to one render pipeline. Infrastructure addresses
on `security` also keeps them in a higher trust tier, the placement
reason OpenBao lives there.

## Decision

A second, dedicated BIND9 instance on `security`, authoritative only
for the A records of Tofu-provisioned VMs, separate from `services`'
zone. It is fed by the inventory generator's output rather than by
`host_vars` or `app_catalog`, and it reuses the render, compare and
reload mechanism of the `bind9` role, as a parameterised version of that
role or a close sibling.

The gateway's Unbound is the single resolver for the VLANs. It forwards
`services`' zone to `services` and the Tofu-hosts zone to `security`,
each by name, so neither BIND instance delegates to the other and
neither needs to know the other exists. No dynamic DNS is involved, and
the gateway runs no authoritative DNS.

## Alternatives considered

- **Static host overrides pushed through the gateway's BIND plugin.**
  Supported, but it makes DNS depend on a live API call during deploy,
  and the plugin leaves the lab only for this.
- **Tofu records in `services`' zone.** Couples two data sources and puts
  infrastructure addresses on an application host.
- **NS delegation from `services`' zone to `security`.** Needs each
  instance to know the other and answers to be reachable by every client
  that asks it directly. A forward in the resolver does the same job at
  one place.

## Assumptions

- **Claim:** Unbound forwarding the two zones to their servers resolves
  names from every VLAN, while it keeps validating public names.
  **Breaks if wrong:** the private zones are marked insecure in Unbound
  or served another way.
  **Checked by:** the resolution test in ADR 0089's spike, then a probe
  from each VLAN.
- **Claim:** a second instance costs less than the coupling it avoids.
  **Breaks if wrong:** it needs handling `services`' does not, such as
  its own deploy order or self-resolution beside OpenBao and step-ca on
  `security`.
  **Checked by:** when the role or module is built.
- **Claim:** every name the lab needs while `security` is down still
  resolves, or is not needed until it is back. Every generated CNAME in
  `services`' zone ends at a record in the Tofu-hosts zone, so that
  zone's one server on `security` is in the path of all of them.
  **Breaks if wrong:** a rebuild of `security`, or any step that needs a
  name before it returns, cannot resolve it; the design then needs a
  second server for the zone on another host, or the CNAME targets kept
  outside it.
  **Checked by:** reading the rebuild and restore order against the names
  each step resolves, then a probe from a VLAN with the `security` server
  stopped.

## Consequences

- `bind9.md` and the README's "single authoritative BIND9 instance"
  framing need updating when a second zone exists.
- [`vm-provisioning.md`](../../topics/infra/vm-provisioning.md)'s OPNsense
  section describes static host overrides and dynamic DNS for the dynamic
  pool. It changes when the gateway is rebuilt under ADR 0089.
- `dns_ddns_target`, the name every generated CNAME points at, is a
  gateway dynamic DNS name today. Once hosts are Tofu-provisioned it
  names a record in the Tofu-hosts zone. That is a change to `bind9.md`
  and `host_vars` for the records stage.

## Invariants

- The gateway holds no zone and no dynamic DNS credential.
- No record for a Tofu-provisioned VM is written by hand.
