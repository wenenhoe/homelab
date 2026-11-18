---
id: EXP-services-host-split
title: "Which of the `services` host's apps should share a host and a network?"
type: exploration
status: open
summary: "Whether the apps on `services` that fetch or parse untrusted content should leave the host that also holds the primary DNS server, and which isolation (a second host, the DMZ, or none) is worth its cost."
topic: security-hardening
related: [ADR-0100, ADR-0114, ADR-0116]
---

# Which of the `services` host's apps should share a host and a network?

`services` (VMID 203, VLAN 20) runs the primary DNS server and a set of utility
apps on one Docker host. Some of those apps fetch from addresses a client names
or process files a client supplies. The question is whether any of them should
run elsewhere, and what would be gained and given up. It cannot be answered yet:
two facts about what the apps can reach are recorded as unknown.

## What bears on it

- **What runs there.** The apps on `services` are `caddy`, `beszel-agent`, `bind9`,
  `bentopdf`, `cobalt`, `dashy`, `kms`, `librespeed`, `shlink` and `wastebin`
  ([`coverage.md`](../topics/disaster-recovery/coverage.md)). `bind9` is the
  primary of every zone, with a secondary on `storage`. `kms` publishes port 1688
  to activation clients, and the flow list expects it reachable from the desktops
  zone ([`network-boundary-checks.md`](../topics/infra/network-boundary-checks.md#the-flows-in-the-list)).
- **Who shares the network.** `services`, `play`, `security`, `storage` and the
  Tailscale router are all in VLAN 20, so a compromised container on `services`
  starts on the same subnet as the secrets store and the backup storage, and
  OPNsense's rules do not apply between them
  ([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#vmid--vlan--ip-scheme)).
- **The two unknowns.** [`cobalt.md`](../topics/records/cobalt.md) records that it
  "fetches whatever address a request names", that its route has no sign-in, and
  that it is unknown whether it can reach other internal addresses.
  [`bentopdf.md`](../topics/records/bentopdf.md) records that it is unknown whether
  the image makes outbound calls. Both can be found by reading the host's Docker
  network and watching the container's traffic.
- **What needs internal reach.** `dashy` makes status-check requests to the
  services it links ([`dashy.md`](../topics/records/dashy.md)), so it needs internal
  addresses and cannot sit in a zone that denies them. `kms` needs inbound from the
  desktops zone, and `bind9` from every zone.
- **What the DMZ is.** [ADR 0114](../decisions/0114-landing-a-series-from-a-device-other-than-the-laptop/revision-000.md)
  defines the DMZ for hosts that parse untrusted content and are reached over the
  tailnet: its interface denies every private range outbound, and nothing inside
  the lab initiates to it. An app moved there would be reached only over the
  tailnet, including from a laptop at home.
- **The DMZ's egress is a proxy allowlist.** ADR 0114 sends the DMZ's Internet
  traffic through the proxy of [ADR 0116](../decisions/0116-internet-egress-for-hosts-in-default-deny-zones/revision-000.md).
  A host-name allowlist cannot list the sites `cobalt` fetches, so an app like it
  would need direct Internet with private ranges denied, which the DMZ as ADR 0114
  defines it does not give.
- **What a new host costs.** A Tofu module and inventory entry, a catalog route set
  under its own `caddy_domain` (so the apps' host names change), a DNS zone, a
  per-host backup credential scoped to its own objects
  ([`services.yaml`](../../ansible/inventory/host_vars/services.yaml) shows the
  pattern), a service record for anything new, and patching. The node's size
  and an early accounting of its headroom are recorded only in decision prose
  ([ADR 0035](../decisions/0035-container-orchestration-platform/revision-000.md)),
  not as a budget kept current, so what one more VM costs is not known.

## Options

- **Leave the host as it is and settle the unknowns.** Read the Docker network and
  watch `cobalt` and `bentopdf`, then record what is true in their service records.
  Costs a check and changes nothing else. If `cobalt` can reach internal addresses
  from a host in VLAN 20, the gap stays open.
- **Split by role inside VLAN 20.** One host for the infrastructure (`caddy`,
  `bind9`, `kms`, `beszel-agent`) and one for the utility apps. Separates the Docker
  hosts, not the network, since both stay in VLAN 20. It costs a host and renames
  every utility app's URL, for a gain limited to a container escape.
- **Move only the apps that fetch or parse untrusted content to a DMZ host.** Today
  that is `cobalt`, and `bentopdf` if its outbound calls turn out to matter. Gives
  a network boundary between them and the rest of VLAN 20. Costs a host, tailnet-only
  reach for the people who use them, and a DMZ egress mode that ADR 0114 does not
  define for an app like `cobalt`.
- **One VM per app.** The strongest separation, at about a host for each of the
  seven utility apps. Lost on cost before it is weighed on gain.
- **Drop or replace the app that carries the risk.** If `cobalt` is not used enough
  to justify a host, removing it ends the question for it.

## Leaning

Settle the two unknowns first, since they cost almost nothing and decide whether
the split is needed. If `cobalt` can reach internal addresses, moving it, alone, to
a DMZ host is the smallest change that adds a network boundary, and the other apps
stay. The proxy decision does not wait on this: nothing in it needs `services` to
change.
