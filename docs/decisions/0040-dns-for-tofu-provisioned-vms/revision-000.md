---
id: ADR-0040
revision: 0
type: adr
title: DNS for Tofu-provisioned VMs
short: Tofu VM DNS
solution: BIND9 on services serves the host records beside the service zones, with a secondary on storage, and the gateway forwards both zones to both servers
summary: How Tofu-provisioned VMs get internal A records when their IPs are fixed at provision time.
topic: deployment-platform
status: accepted
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
- On the scratch gateway, a forward to a server holding an unsigned zone
  answered names with private and public addresses and NXDOMAIN for
  missing names, without the authenticated-data flag, because Unbound's
  templates write `domain-insecure` for a forwarded domain and, unless the
  GUI's rebind check is off, `private-domain`. Names under no forward kept
  validating in Unbound 1.24.2, though not on the gateway, which had no
  route to the roots. The two zones are unsigned, so they are answered
  but not validated.
- `services` is rebuilt after every other host, because every host
  resolves through its BIND9. The deploy that precedes a restore brings
  that BIND9 up from `host_vars` before any app is restored, so the
  storage endpoint name the restore reads resolves again once the deploy
  has run.
- OPNsense 26.1.6 writes one `forward-zone` per domain, with a
  `forward-addr` line for each forward entry of that domain. Unbound sends
  a forwarded query to those addresses as a recursive query and chases a
  CNAME itself, asking the forwarder for every name in the chain.
- Unbound 1.24.2 on the gateway queries any address of a `forward-zone`,
  not the first one listed: with both servers up it used both. In one run
  each, with one server stopped and with it reachable but never
  answering, a host name, a service name and a CNAME from one forwarded
  zone to the other were all answered from the remaining address. A query
  that went first to the dead server waited about 0.4 s, from a state in
  which Unbound held no record of its servers' response times; the CNAME
  across the two zones took 1.2 s when the server never answered, and
  every later query took milliseconds. A server that answered again
  received no query from Unbound for the next three minutes.
- The `bind9` role's zone files carry an epoch serial that is written
  only when the content changes, so a secondary sees a new serial for a
  real change alone.

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
Tofu does not provision: the Proxmox node and the gateway, and each
current host until Tofu rebuilds it. Every service CNAME points at its host's
`host_fqdn`, `<inventory host name>.<host_domain>.`, computed once for all
hosts; no host carries a per-host variable for it.

A second BIND9 on `storage` is a secondary for both zones. It takes them
from `services` by zone transfer, authenticated with a TSIG key from the
secret catalog, and `services` allows transfers to that key alone. The
secondary is in place, and a live loss of `services` has been survived,
before the first Tofu rebuild, so the rebuild of `services` leaves the
lab's internal names served.

The gateway's Unbound is the single resolver for the VLANs. It forwards
`host_domain` and `lan_domain` to both servers. No dynamic DNS is
involved, and the gateway runs no authoritative DNS: the live gateway's
BIND9 zone and dynamic DNS are retired once `services` serves the host
zone with a static record for every host, so a host no longer gets its
name from a lease.

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
- **One server until the secondary exists.** The gateway's cache only
  keeps what a record's TTL allows, and the collection has no field for
  OPNsense's serve-expired setting, so a rebuild of `services` would leave
  every rebuilt host without internal names for its length.
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

## Consequences

- The gateway spreads queries over both servers, so `storage` answers a
  share of them while `services` is up. A change to a zone reaches
  `storage` by notify and transfer, and until it arrives some clients are
  answered from the old data. A server that returns is not used again at
  once.
- Retiring dynamic DNS ends the names the `.50`–`.254` DHCP clients get
  from leases, until a later decision gives them another source.
- The gateway's play connects by the gateway's management name, whose
  record is a static one in the host zone. A rebuilt gateway has no
  forward until that play has run, so the operator host resolves the name
  another way for the first run.
- A rebuilt host's `ansible_host` is its address, so Ansible no longer
  resolves a host name that the DNS role it is about to run provides.
- The names of the `.50`–`.254` DHCP clients are not settled here.

## Invariants

- The gateway holds no zone and no dynamic DNS credential.
- No record for a Tofu-provisioned VM is written by hand.
