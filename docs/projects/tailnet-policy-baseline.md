---
id: PROJ-tailnet-policy-baseline
title: Tailnet Policy Baseline
type: project
status: not-started
blocked: false
summary: Replace the tailnet's allow-all policy with explicit grants and tests, once, so the projects that add a route only add a grant.
---

# Tailnet Policy Baseline

The tailnet's policy is the default allow-all grant. Two projects need to tighten it before they advertise a route ([`operator-host.md`](operator-host.md) for VLAN 30 and [`coding-agent-network.md`](coding-agent-network.md) for the coding-agent VLAN), and each used to say that whichever went first replaces it. This project makes that one change once, so each of them only adds a grant, and the policy has a single owner until it is coded.

## Scope

Taking stock of what the maintainer reaches over the tailnet today, and of what else the tailnet holds (its devices, its DNS settings and the policy's other sections), and replacing the allow-all grant with explicit grants for exactly that, plus `tests` that assert them, and the entries the subnet router's tag needs: a `tagOwners` entry for the tag and an `autoApprovers` entry for the route the router already advertises ([ADR 0097 (Tailscale node configuration)](../decisions/0097-how-a-tailscale-node-is-configured/revision-000.md)). Not in scope: any new route's grant and auto-approval entry ([`operator-host.md`](operator-host.md), [`coding-agent-network.md`](coding-agent-network.md)), and putting the policy under Tofu, which builds on Tofu's root module ([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#tofu-project), [ADR 0059 (Tailnet policy)](../decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md)).

## Decision

No decision of its own. [ADR 0059 (Tailnet policy)](../decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md) decides that the policy is hand-edited in the console now and coded later, and this project is the hand edit. It names no `decision:` because that revision is `working` on an assumption about the Tofu provider, which this work does not touch.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Take stock of what the maintainer and the nodes reach over the tailnet today, and of the tailnet's devices, DNS settings and other policy sections | Not started | Every source, destination and port in use is listed in a topic doc, with how it was found, and so is every device, nameserver and non-grant policy section, each matched to something the lab uses or marked for removal |
| 2 | Clean up the devices, then replace allow-all with explicit grants and `tests` | Not started | Every device marked for removal is gone, the saved policy grants exactly what Stage 1 lists, its `tests` pass, every flow in the list still works from the node that uses it, and the policy holds the router's tag under `tagOwners` and its existing route under `autoApprovers`, with no node yet carrying the tag |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — what the inventory covers

- **Devices.** Match each device in the console to a machine the maintainer owns and still uses. A device whose key has expired, one that has not connected for months, and one that stands for a retired machine is marked for removal. The topic doc describes devices by role, never by name or address, and the maintainer removes them in the console. Each remaining user-owned device's key expiry is a recorded choice, since an expired key drops a device off the tailnet.
- **The Proxmox node.** It is a member and the way to the hypervisor when the router VM is broken, so Stage 2 keeps one grant to it from the maintainer's devices alone, and the inventory records how it joined and whether it should carry a tag of its own. [`proxmox-node-install.md`](proxmox-node-install.md) owns restoring that membership after a reinstall.
- **DNS.** Record MagicDNS, the global nameservers and each split-DNS entry with every nameserver it lists. A nameserver the tailnet's resolver can reach has to sit inside a route the router advertises, and each needs a grant on port 53 from the devices that resolve through it, or tightening the policy breaks name resolution. The internal zones list the gateway today, which forwards to both servers of [ADR 0040 (Tofu VM DNS)](../decisions/0040-dns-for-tofu-provisioned-vms/revision-000.md). Stage 1 records whether to list the secondary beside it once it exists, so that losing one resolver does not take the zones away.
- **The policy's other sections.** The default policy carries a Tailscale SSH rule and a Funnel attribute besides its grant. Each is kept only if Stage 1 finds a use for it, since [ADR 0097](../decisions/0097-how-a-tailscale-node-is-configured/revision-000.md) leaves Tailscale SSH and Funnel out.

### Stage 2 — the edit

Copy the current policy first, and use the admin console's preview before saving. The policy is tailnet-wide, so an edit that tightens access can lock out existing access; "Reset to default" restores the allow-all grant. Add `tests` for each grant and for what must stay refused. A route is advertised or approved only after the saved policy grants it to the intended source alone, since while allow-all is in force every tailnet node would reach it.

## Acceptance criteria

- [ ] The policy is no longer allow-all, and every flow Stage 1 lists still works.
- [ ] `tests` assert each grant, and a save with a failing assertion is refused by the console.
- [ ] The policy names the router's tag in `tagOwners` and auto-approves the route the router advertises under it, so the router's rebuild ([`tofu-migration.md`](tofu-migration.md)) joins under a tag the policy already knows.
- [ ] The topic doc names who adds a grant, and an auto-approval entry, for a new route and how.
- [ ] No device is left that Stage 1 could not match to a machine in use, and the topic doc records every nameserver the tailnet lists and the grant that lets each be reached.
- [ ] No source in the tailnet has a grant to the router's own address unless Stage 1 found a use for one, since the host is managed from the operator host through the gateway and not over the tailnet.

## Risks

- An edit that tightens access can lock out the maintainer or a node; the previous policy is copied first and the console's reset restores allow-all.
- Stage 1 can miss a flow that is used rarely; the exit lists how each was found, and a missed one is re-granted from the copy.

## Open items

- Where the topic doc lives; probably with [`network-infra.md`](../topics/infra/network-infra.md).

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
