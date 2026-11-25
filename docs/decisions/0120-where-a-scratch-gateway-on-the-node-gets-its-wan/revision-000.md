---
id: ADR-0120
revision: 0
type: adr
title: Where a scratch gateway on the node gets its WAN
short: Scratch gateway WAN
solution: A zone of its own on VLAN 10 that leases the scratch gateway a route out and the gateway's resolver, and lets that one address reach the node's SSH and API ports
summary: Where the WAN of a scratch gateway on the node backend comes from now that the production gateway serves no untagged network, what the zone that serves it may reach, and how the scratch seed keeps it out of its own interfaces.
topic: deployment-platform
status: approved
related: [ADR-0089, ADR-0094, ADR-0116]
relies_on:
  - adr: ADR-0089
    reason: "The zone's interface comes from the seed and its rules, scope and aliases from the play."
---

# 0120. Where a scratch gateway on the node gets its WAN

## Problem

A scratch gateway on the node needs a WAN that gives it an address, a route to the Internet and a resolver, so that it can update its firmware, and, for a run that shows a boundary to the node, a path to the node's management ports. The WAN must not give the test bed more reach than those two needs, and it must not collide with the networks the scratch gateway itself carries.

## Context

- **The old WAN is gone.** A scratch gateway took its WAN from `WAN_BRIDGE`, untagged unless `WAN_VLAN_ID` was set, and until the production gateway was rebuilt the untagged network was served by it. The rebuilt gateway retires that network: it holds one rule there, which admits the operator host to the GUI port, and Kea has no scope for it. A WAN there gets no lease, and an address given by hand would still have no rule that passes it out.
- **A production VLAN as the WAN overlaps a seeded interface.** A scratch gateway carries every production VLAN as `192.168.<vlan>.1/24` on its own LAN bridge, and the play names each zone's interface by the VLAN's position in the seed's list. A WAN leased from VLAN N is in the `/24` of the seeded interface for N. Leaving N out of a run's seed shifts the positions after it.
- **A zone with Internet, DHCP and the gateway's resolver is enough for the update.** A scratch gateway on VLAN 55 with that tag left out of its seed leased an address, reached the gateway, got a route and the gateway's resolver once the scopes offered them, and reached the update mirror. The firmware status took about 70 seconds there.
- **The node's controls need a path to the node.** The `coding-zone` and `dmz-probe` runs show that a host in the coding-agent zone or the DMZ is refused the node's SSH and API ports. A refusal counts only beside a control, a desktops canary that connects to the same port, so the scratch gateway's WAN has to reach the node on 22 and 8006 and the node has to answer it. Every zone's Internet rule excludes the private ranges, which hold the node's management address.
- **A new zone costs an edit to the seed.** On the pinned 26.1 series the gateway's API cannot assign a VLAN device to an interface or give it an address; the seed does, at first boot only ([ADR 0089](../0089-how-the-opnsense-gateway-is-configured/revision-000.md)). The production gateway gains an interface when it is next built from the seed.
- **The WAN's address can be reserved.** A NIC's MAC is derived from its VMID and index ([`vm-provisioning.md`](../../topics/infra/vm-provisioning.md#mac-address-scheme)), so the scratch gateway's WAN, VMID 501 by default, always has the same MAC and Kea can reserve one address for it.
- **VLAN 45 is taken.** The egress proxies are to sit in it ([ADR 0116](../0116-internet-egress-for-hosts-in-default-deny-zones/revision-000.md)). VLAN 10 is outside every seeded tag and outside the VMID scheme's networked blocks, which start at 200.

## Decision

The production gateway gets a zone, `scratch_wan`, on VLAN 10 (`192.168.10.0/24`), the seed's ninth interface. It is written by the play and leaves the other zones alone.

- **Address and route.** Kea serves it a scope with the gateway as router and resolver, as it does every zone it serves.
- **Internet.** It has the rule every zone with Internet has: everything outside the private ranges, and no direct DNS.
- **The node.** A rule passes the scratch gateway's reserved address, one address in the zone, to the node's management address on 22 and 8006. No other source in the zone has it.
- **Nothing else.** No flow leaves the zone for another zone, and none enters it.

The scratch seed leaves VLAN 10 out, so a scratch gateway has no interface that overlaps its WAN. The kit sets `WAN_BRIDGE=vmbr1` and `WAN_VLAN_ID=10` by default, and the runs play the zone switched off, since a scratch gateway has no ninth interface.

## Alternatives considered

- **A production zone's VLAN, with its tag left out of the run's seed.** VLAN 55 worked for the update. Leaving it out costs every run its experimental-zone coverage and shifts the interfaces after it, and the node's controls still have no path.
- **VLAN 45.** Free in the scheme, but taken by the egress proxies, which are a different trust level from a test bed's WAN.
- **A static WAN in the scratch kit.** It removes the lease and nothing else: the untagged network has no rule that passes the traffic, and in a zone's VLAN the address still sits in a seeded `/24`.
- **A range and a rule made by hand on the untagged network.** Neither is in the play, and the network is meant to retire.
- **A resolver alone.** It fixes the DNS half; nothing leases the WAN.
- **The QEMU backend alone.** It has its own WAN but no route to the node, so a run that needs the node cannot build there.

## Consequences

- The production gateway carries a standing network that exists for the test bed, and a rule that admits one address to the node's management ports.
- The zone exists on the production gateway only after it is rebuilt from the seed. Until then a run that needs only the update can use VLAN 55 with that tag left out of its seed.
- The seed's default list and the scratch default differ by one tag, and a test pins the difference.

## Invariants

- No flow leaves the zone for another zone, and none enters it.
- Only the scratch gateway's reserved address reaches the node, and only on 22 and 8006.
- The scratch seed never carries VLAN 10.

## Non-goals

- The QEMU backend's WAN, which already works without the node.
- A WAN for any host other than a scratch gateway.

## Validation

The tests that compare the play's zone list with the seed, and one that pins the difference between the production and scratch seeds, keep the two lists in step. The flow list holds the zone's flows, and `coding-zone` and `dmz-probe` pass their node controls through it.

## Reconsideration triggers

A second user of the node backend that needs a WAN of its own, a gateway release whose API assigns interfaces, or a run that fails at the play with the zone switched off.
