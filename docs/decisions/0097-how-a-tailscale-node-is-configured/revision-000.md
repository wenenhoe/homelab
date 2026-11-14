---
id: ADR-0097
revision: 0
type: adr
title: How a Tailscale node is configured
short: Tailscale node configuration
solution: A small repo-owned role converges the node against its own preferences and joins it, tagged, with a one-time key supplied at run time
summary: How a host's Tailscale client is installed, joined to the tailnet and kept configured, given that the join key is a credential and the policy keys off the node's tag.
topic: deployment-platform
status: superseded
superseded_by: 1
related: [ADR-0109, ADR-0040, ADR-0043, ADR-0049, ADR-0053, ADR-0058, ADR-0059, ADR-0089]
relies_on:
  - adr: ADR-0058
    reason: "It sizes the subnet router as always on because the operator host is reached only through a Tailscale route to VLAN 30, which ADR 0058 makes so."
---

# 0097. How a Tailscale node is configured

## Problem

The tailnet is the maintainer's path into the lab away from home, and the subnet router is the one node that carries it. That node's installation, join and preferences have to be rebuildable from the repository, and the credential that joins it has to be handled without a standing secret. The tailnet's own policy is a separate problem ([ADR 0059 (Tailnet policy)](../0059-where-the-tailnet-policy-is-defined/revision-000.md)); this one is the node.

## Decision

**A repo-owned role**, `tailscale_node`, applied to the `network_infra` group. No collection is a dependency.

The role converges, in order:

1. **Install** from Tailscale's apt repository in the same DEB822 form the `docker` role uses for Docker's, and start `tailscaled`. Where the node has the vendor script's one-line source, the role removes that file in the same run, so apt does not see the repository twice.
2. **Forwarding.** When the node advertises routes, a sysctl drop-in sets IPv4 and IPv6 forwarding.
3. **Join**, only when the node is logged out. The role then requires a one-time key and passes it with the node's tag. A node that is already logged in needs no key, and a missing key on a logged-out node stops the play before anything changes.
4. **Preferences**, compared against what the node reports and applied with `tailscale set` for each one that differs. The role names every preference it owns: the advertised routes, the accepted DNS setting, and the client's auto-update, which is off. Source NAT stays at its default.

**The tag and the routes.** The node joins with one tag, `tagOwners` names the maintainer as its owner, and `autoApprovers` approves the routes it advertises. Both live in the tailnet policy, which is written by hand in the console ([`tailnet-policy.md`](../../topics/infra/tailnet-policy.md)) and which [ADR 0059](../0059-where-the-tailnet-policy-is-defined/revision-000.md) later carries into OpenTofu unchanged. The routes the node advertises are a host variable, so a new zone's route is a change to that variable and one grant in the policy.

**The join key** is made in the Tailscale admin console for the rebuild: single-use, pre-authorized, tagged, and valid for hours. It reaches the play as a run-time variable from the operator's environment, is not logged, and is not written anywhere.

**Updates.** Only apt updates Tailscale, through `maintenance.yaml`, one host at a time like every other package. The client's own updater is off, and the host's unattended upgrades take security origins only ([ADR 0043 (Host hardening baseline)](../0043-host-os-hardening-baseline/revision-000.md)), so a Tailscale release reaches the router when that play runs against `network_infra` and not before.

**What Molecule covers.** The install, the forwarding drop-in, the preference comparison against a stub client whose output is copied from a real node, and the refusal to join without a key. The join itself needs a control plane, so it is checked on a real node, and a `--check` run after it reports no change.

## Invariants

- No Tailscale auth key or OAuth secret is in the repository, OpenBao, Tofu's state or a role default. A key exists only for the run that joins the node.
- A subnet router joins tagged, never as a user's device.
- The router keeps source NAT on while the gateway's rules identify tailnet callers by its address.
- Only apt updates Tailscale on a node.

## Non-goals

- The tailnet's policy, DNS and devices other than the node's own ([ADR 0059](../0059-where-the-tailnet-policy-is-defined/revision-000.md)).
- Exit nodes, Tailscale SSH, Serve and Funnel.
- Whether the GCP node joins the tailnet. It may use this role if it does, decided with its own project.
- Whether the Proxmox node's membership is configured by this role. [`proxmox-node-install.md`](../../projects/proxmox-node-install.md) decides that with its inventory of the node.

## Reconsideration triggers

- A published role or collection converges a node against its actual preferences and joins only when the node is logged out.
