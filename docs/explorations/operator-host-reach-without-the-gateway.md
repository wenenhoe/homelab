---
id: EXP-operator-host-reach-without-the-gateway
title: "How does the operator host reach the node while the gateway is down?"
type: exploration
status: open
summary: "The operator host sits behind the gateway, so a gateway rebuild cuts it off from the node, the lab's DNS and the Internet; which path, if any, should it keep for that time."
topic: deployment-platform
related: [ADR-0058, ADR-0089, ADR-0103]
---

# How does the operator host reach the node while the gateway is down?

Rebuilding or repairing the gateway stops it, and the operator host runs behind it. Whatever the work needs from the node has to come over some path that does not cross the gateway for as long as it is down, or the work waits for the gateway to return. The one rebuild so far moved the operator host's NIC to the physical bridge for the window. Whether that stays the way, or the host keeps a standing path, is not decided.

## What bears on it

- VM 401 is in VLAN 40 and VM 252 is planned in VLAN 25. Both reach the node's SSH and API, the host zone's DNS and the Internet through the gateway's rules, so with it stopped they reach none of them.
- A gateway rebuild stops it from the dump until the update is done, and the rest of the lab is offline for that time too.
- The node-side steps (`qm`, `retire_vm.sh`, the first-boot script) need only SSH to the node. The Tofu create needs the Proxmox API and Tofu's state, which is held in an R2 bucket ([ADR 0103](../decisions/0103-where-tofus-state-is-held/revision-000.md)), so it also needs the Internet. The provider plugins are cached after an `init`.
- The Proxmox endpoint is addressed by name, and a connection by the node's IP address failed certificate verification, so the host needs the name to resolve without the gateway's DNS (a hosts-file entry did it).
- The update script and the play reach the gateway on the LAN, so they come after the host has returned to it.
- The gateway's rules decide today which hosts reach the node. A path that does not cross the gateway is not subject to them.

Still to check: whether the node's firewall is on and what it would hold for a second address; whether the node's web proxy answers on an address of a new bridge; and where the operator-host project plans the node's reach from VLAN 25.

## Options

- **Keep the detour, written as a procedure.** The host's NIC moves to the physical bridge for the window, with a hosts entry for the node's name and a fixed address for its return. No new standing path and nothing to maintain, and it was shown to work. It stays manual, needs a person at the node's console to move the NIC, and gives the host the Internet and the physical network for the window.
- **A bridge with no uplink for the operator host.** A second NIC on a bridge with no physical port, and an address for the node on it. The host reaches the node's SSH and API without the Internet or the physical network. The Tofu steps then have no route to the state bucket, so they would need another answer (a local state for the window, or a relay on the node), and the node's own network configuration changes. The path bypasses the gateway's rules, so the node's firewall would have to admit only the operator host's address on it.
- **The same bridge with the node forwarding out.** The node would NAT the operator host to the Internet. It restores the Tofu steps, but it makes the node a second gateway for one host, which contradicts the reason for the isolated bridge, so it is kept only as the variant that fails.
- **Work from a device on the physical network.** A laptop on the physical network runs the window's steps. It needs the credentials and the state backend there, which widens where they are held ([ADR 0058](../decisions/0058-where-operator-work-runs/revision-000.md) is about where the work runs).

## Leaning

The detour, written down and scripted, while rebuilds are rare. An isolated bridge becomes worth its cost if the gateway has to be stopped often, or if the operator host's Internet during a rebuild turns out to matter; it first needs an answer for the state bucket. Finding that the node's address on a new bridge cannot be firewalled to one host would remove it.
