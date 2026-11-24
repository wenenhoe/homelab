---
id: EXP-scratch-gateway-wan
title: "How does a scratch gateway on the node get a usable WAN now that the production gateway no longer serves the untagged network?"
type: exploration
status: open
summary: "A scratch gateway's WAN on an untagged bridge no longer gets an address, route or resolver from the rebuilt production gateway, so a gateway-building run on the node backend cannot reach its update mirror; where the WAN should come from, and what each source costs."
topic: deployment-platform
related: [ADR-0089, ADR-0094]
---

# How does a scratch gateway on the node get a usable WAN now that the production gateway no longer serves the untagged network?

A scratch gateway on the node backend takes its WAN from `WAN_BRIDGE`, untagged unless `WAN_VLAN_ID` is set, and until the production gateway was rebuilt that network was served by the production gateway's untagged `lan`. The rebuilt gateway retires that network and its DHCP range, and every zone is refused direct DNS on 53 and 853. A run that builds a gateway there stops at the step that updates it, so every run on the node backend that builds a gateway is blocked, the [`coding-zone`](../topics/infra/scratch-gateway-runs.md#the-coding-agent-zone-run) run among them. What the WAN should be served by is not decided.

## What bears on it

- The play writes no DHCP range and no rules for the untagged `lan`, and removes firewall rules it does not write ([`opnsense-gateway.md`](../topics/infra/tofu/opnsense-gateway.md)). An untagged WAN therefore has no one to lease it an address.
- Every zone's direct DNS is blocked. A WAN that does get an address still needs a resolver it is allowed to reach, or the update mirror's name does not resolve.
- A scratch gateway's LAN is seeded with every production VLAN (20, 25, 30, 35, 40, 45, 50 and 55), so a WAN on a tagged VLAN that is one of those collides with a seeded network on the same bridge.
- The mirror itself answers from the operator's machine, so the block is on the path from the scratch gateway, not at the mirror.
- The QEMU backend's WAN is user-mode networking and reaches the Internet, but has no route to the node, so the controls that need the node fail there. It does not stand in for the node backend.
- The scratch kit (`scratch_gateway.sh`, `scratch_run`) sets the WAN's addressing by DHCP only.

Still to check, on the production gateway: whether the scratch gateway's WAN asked for a lease and was refused or never seen, and which rule, if any, dropped its DNS. The production gateway's DHCP leases and its firewall log would settle it. Until then the untagged network's retirement is the likelier cause and the DNS block a second one.

## Options

- **A WAN VLAN outside the seeded list.** The production gateway serves one more VLAN for scratch WANs, with DHCP, a route out and a resolver the zone may reach. The seeded list stays as it is. It changes the production gateway's play for the sake of a test bed, and the VLAN is a standing network that exists only for it.
- **A temporary range on the untagged network.** A hand-made DHCP range is added while a run lasts. It works at once and contradicts the statement that the network retires; a hand-made change also is not in the play, so the next apply removes it.
- **Static WAN addressing in the scratch kit.** The kit gives the scratch gateway a fixed WAN address, route and resolver from the settings file, and no network has to lease it anything. It needs an address the bridge's network is known not to use, and the kit's seed has to carry the values. It is a change to the scratch kit's own tools and tests.
- **A resolver the scratch gateway is allowed to reach.** Only the DNS half is fixed: the WAN's lease or the seed names a resolver that the production gateway lets through. It does not help while nothing leases the WAN.
- **Run the update from the QEMU backend only.** Runs that need no node controls use the QEMU backend, which has its own WAN. It leaves a run that needs the node, such as the zone run's VM canary, with no way to build.

## Leaning

None yet. The first thing to settle is the cause, from the production gateway's leases and log. If the retirement is the cause, a static WAN in the kit costs the production gateway nothing and keeps the zone's rules out of its play; a WAN VLAN is weighed again if a second user of the node backend wants a WAN that behaves like a zone.
