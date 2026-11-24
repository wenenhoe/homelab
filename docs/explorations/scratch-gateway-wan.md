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

A scratch gateway on the node backend takes its WAN from `WAN_BRIDGE`, untagged unless `WAN_VLAN_ID` is set, and until the production gateway was rebuilt that network was served by the production gateway's untagged `lan`. The rebuilt gateway retires that network, and the network has neither a DHCP range nor a rule that passes its traffic out. A run that builds a gateway there stops at the step that updates it, so every run on the node backend that builds a gateway is blocked, the [`coding-zone`](../topics/infra/scratch-gateway-runs.md#the-coding-agent-zone-run) run among them. What the WAN should be served by is not decided.

## What bears on it

- The play writes no DHCP range and no rules for the untagged `lan`, and the seed removes the sample's allow-all rules from it, leaving one rule that admits the operator host to the gateway's GUI port ([`opnsense-vm.md`](../topics/infra/tofu/opnsense-vm.md), [`opnsense-gateway.md`](../topics/infra/tofu/opnsense-gateway.md)). An untagged WAN has no one to lease it an address, and an address it was given by hand would still have no rule to pass it out.
- A scratch gateway's LAN is on its own bridge (`vmbr9` or `vmbr8`), not on the WAN's, and carries every production VLAN (20, 25, 30, 35, 40, 45, 50 and 55) as `192.168.<vlan>.1/24`. A WAN leased from a production VLAN is in that VLAN's `/24`, so it overlaps the seeded interface for the same tag inside the scratch gateway. Every spec that sets `gateway.vlans` lists all eight.
- The production zones with a DHCP range are desktops (40), isolated (50) and experimental (55). Only desktops and experimental pass traffic to the Internet, both with the gateway's resolver.
- The play blocks direct DNS on 53 and 853 from every zone with Internet, at a later sequence than the rules that pass the gateway's own resolver ([`policy.yaml`](../../ansible/roles/opnsense_gateway/tasks/policy.yaml)). The block therefore bites a resolver other than the gateway, and a WAN in such a zone can resolve through the gateway. `dhcp.yaml` names no DNS option, so what a lease names as resolver is not yet known.
- Two runs, [`coding-zone`](../../tofu/scratch/opnsense/runs/coding-zone.yaml) and [`dmz-probe`](../../tofu/scratch/opnsense/runs/dmz-probe.yaml), also need the WAN to reach the node (`10.0.0.254`) on 22 and 8006 for their controls. Every zone's Internet rule excludes the private ranges, so a WAN in a production zone reaches the update mirror and not the node. The other runs need only the update.
- The play's zones name interfaces the seed creates, and the scratch seed's default list is the production list. A further production VLAN is therefore a change to the seed as well as to the play.
- The mirror itself answers from the operator's machine, so the block is on the path from the scratch gateway, not at the mirror.
- The QEMU backend's WAN is user-mode networking and reaches the Internet, but has no route to the node, so the controls that need the node fail there. It does not stand in for the node backend.
- The scratch kit (`scratch_gateway.sh`, `scratch_run`) sets the WAN's addressing by DHCP only.

Still to check, on the production gateway: that the untagged interface has the rules the seed's note says it has and no lease range, and, for a candidate zone, what resolver its leases name. The gateway's DHCP leases and rule list would settle both. The repository's own description of the untagged network already accounts for the block; the log would show whether the DNS block is a second cause.

## Options

- **A WAN VLAN outside the seeded list.** The production gateway serves one more VLAN for scratch WANs, with DHCP, a route out, the gateway's resolver and, if the node controls are wanted, a rule to the node on 22 and 8006. The scratch seed's list stays as it is, so the new tag has to be in the production seed and not in the scratch default, and the two lists no longer match. It changes the production seed and play for the sake of a test bed, and the VLAN is a standing network that exists only for it.
- **A production zone's VLAN for the WAN, with that tag left out of the run's seed.** Experimental (55) already has a DHCP range, a route out and the gateway's resolver, so an update-only run could set `WAN_VLAN_ID=55` and seed without 55. The production gateway does not change. The run's `gateway.vlans` and its zone list would have to drop `experimental` (opt8) and the `vlans` step's count follow, so those specs would differ from the seed's own list, and a run that needs the node controls still has no way to the node. The experimental zone gets a scratch gateway as a client, which is the kind of host it is for.
- **A temporary range on the untagged network.** A hand-made DHCP range and a hand-made pass rule are added while a run lasts. It works at once and contradicts the statement that the network retires; neither is in the play, and it needs both, since a range alone gives no route.
- **Static WAN addressing in the scratch kit.** The kit gives the scratch gateway a fixed WAN address, route and resolver from the settings file. It removes the lease and nothing else: on the untagged network there is still no rule to pass the traffic, and in a production zone's VLAN the address must sit outside the Kea pool (`.10` to `.245`) and still overlaps the seeded tag. It is a change to the scratch kit's own tools and tests.
- **A resolver the scratch gateway is allowed to reach.** Only the DNS half, and the gateway's own resolver is already let through in a zone with `gateway_dns`. It does not help while nothing leases the WAN.
- **Run the update from the QEMU backend only.** Runs that need no node controls use the QEMU backend, which has its own WAN. It leaves a run that needs the node, such as the zone run's VM canary and its node controls, with no way to build.

## Leaning

None yet, but the static WAN no longer leads: the untagged network lacks a rule as well as a lease, so a fixed address does not reach the mirror. What separates the remaining options is whether the runs that need the node controls (`coding-zone`, `dmz-probe`) keep them. If they do not, a production zone's VLAN with its tag left out of the seed costs the production gateway nothing. If they do, the production gateway needs a rule to the node for the scratch WAN, and a dedicated WAN VLAN carries it more cleanly than widening a zone that hosts other things. The leases and the rule list on the production gateway should be read first.
