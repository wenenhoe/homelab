---
id: ADR-0040
revision: 0
type: adr
title: DNS for Tofu-provisioned VMs
short: Tofu VM DNS
solution: One authoritative BIND9 on services serves the host records, built from the Tofu-to-Ansible inventory, beside the service zones, with the gateway forwarding both to it
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
  an app host's `host_vars`, or as a CNAME for a `caddy` route. It
  therefore needs a step that builds A records from the generated hosts;
  it cannot take them from `host_vars`.
- Every host's name today is `<host>.<ddns_domain>`, a record the gateway
  registers. Each app host's `dns_ddns_target` repeats it, `<host>.<ddns_domain>.`,
  from the inventory name and the domain, and every generated CNAME points
  at it. Hosts Tofu does not provision, the Proxmox node and the gateway,
  have names under the same domain, which the dashboard links to.
- [ADR 0089 (OPNsense configuration)](../0089-how-the-opnsense-gateway-is-configured/revision-000.md)
  drops dynamic DNS and the BIND plugin from the gateway. Its Unbound
  recurses directly and can forward a named zone to a given server and
  port.
- `services` is rebuilt after every other host, because every host
  resolves through its BIND9.

The `bind9` role already merges `host_vars` and each app's routes in one
run, and the generated inventory lands in the same hostvars, so the
generated hosts are one more input to that run, not a second pipeline. A
record's integrity matters as much in the service zones as in the host
zone: whoever can write either redirects traffic. `security` holds the
secrets store and the CA, and a network daemon answering for every VLAN
does not belong beside them.

## Decision

The existing BIND9 on `services` stays the single authoritative server.
It serves the service zones as today and one more zone, the host zone,
whose domain is `host_domain` (today `internal.<main_domain>`, a sibling
of `lan_domain`, the parent of the service zones). The `bind9` role
builds the host zone's records from the generated inventory (the host
name and its `ansible_host`) and from static `extra_records` for hosts
Tofu does not provision: the Proxmox node, the gateway, and `tailscale`
while Tofu has not yet built it. Every service CNAME points at its host's
`host_fqdn`, `<inventory host name>.<host_domain>.`, computed once for all
hosts; no host carries a per-host variable for it.

The gateway's Unbound is the single resolver for the VLANs. It forwards
`host_domain` and `lan_domain` to `services`. No dynamic DNS is involved,
and the gateway runs no authoritative DNS.

A secondary for both zones on `storage` is intended as a later,
separate piece of work, not part of this decision. It needs a
zone-transfer credential, which is a decision of its own, and it matters
only while `services` is being rebuilt or is down. Until then Unbound's
cache covers short outages.

The variables are renamed to say what they hold: `ddns_domain` becomes
`host_domain`, `lab_domain` becomes `lan_domain`, and `dns_ddns_target`
becomes `host_fqdn`. `main_domain` keeps its name, since its secret key
is stored in OpenBao.

## Alternatives considered

- **Static host overrides pushed through the gateway's BIND plugin.**
  Supported, but it makes DNS depend on a live API call during deploy,
  and the plugin leaves the lab only for this.
- **NS delegation from `services`' zone to a second server.** Needs each
  instance to know the other and answers to be reachable by every client
  that asks it directly. A forward in the resolver does the same job at
  one place.
- **A second BIND9 on `security` for the host zone.** It splits one data
  set across two hosts for a trust tier that does not hold, since a
  record is as sensitive in either zone, and it puts every CNAME's target
  behind the host that holds the secrets store and CA.
- **`tailscale` as a second server.** It has no Docker, so it needs a
  second deploy path for BIND, the role rewrites the host's resolver
  configuration on a host where `tailscaled` manages DNS, and it is the
  remote-access path.
- **A container on the Proxmox node.** It shares the node's kernel and
  needs its own provisioning and a wider API token, which is a security
  boundary and its own decision.
- **The host zone under `lan_domain`.** One tree and one forward fewer, but
  it reserves a label in the namespace the per-host service zones share and
  renames every host.

## Assumptions

- **Claim:** Unbound forwarding the two zones to `services` resolves names
  from every VLAN, while it keeps validating public names.
  **Breaks if wrong:** the private zones are marked insecure in Unbound
  or served another way.
  **Checked by:** the resolution test in ADR 0089's spike, then a probe
  from each VLAN.
- **Claim:** every name the lab needs while `services` is being rebuilt
  still resolves from the gateway's cache, or is not needed until it is
  back. It is the only authoritative server for both zones.
  **Breaks if wrong:** the secondary on `storage` is needed before that
  rebuild, not after.
  **Checked by:** reading the rebuild and restore order against the names
  each step resolves, then a probe from a VLAN with the server stopped,
  including whether the gateway's Unbound can answer from expired cache
  entries.

## Consequences

- `bind9.md` describes the host zone, its generated and static records,
  and the computed `host_fqdn`. The README's "single authoritative BIND9
  instance" framing stays true.
- [`vm-provisioning.md`](../../topics/infra/vm-provisioning.md)'s OPNsense
  section describes static host overrides and dynamic DNS for the dynamic
  pool. It changes when the gateway is rebuilt under ADR 0089.
- A rebuilt host's `ansible_host` is its address, so Ansible no longer
  resolves a host name that the DNS role it is about to run provides.
- `ddns_domain`, `lab_domain` and `dns_ddns_target` are renamed across
  the inventory, `host_vars`, roles, tests and docs, and the VM module's
  `dns_domain` is `host_domain`. The names of the `.50`–`.254` DHCP
  clients are not settled here.

## Invariants

- The gateway holds no zone and no dynamic DNS credential.
- No record for a Tofu-provisioned VM is written by hand.
