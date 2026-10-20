---
id: PROJ-coding-agent-network
title: Coding-Agent Network Zone
type: project
status: de-risking
blocked: false
summary: A dedicated VLAN, default-deny firewall policy and laptop-only Tailscale route for the coding-agent host, after the spikes that settle ADR 0053's assumptions.
decision: ADR-0053/0
super_project: coding-agent-host
track: boundary
phase: 1-network
---

# Coding-Agent Network Zone

Builds the zone the coding-agent host lives behind, before the host exists: the VLAN, its default-deny rules and the laptop-only route. Staged because three assumptions in the decision (egress proxy feasibility, bridge isolation, resolver design) must be answered before rules are built on them.

The egress proxy and the canary probes that check the whole boundary are [`coding-agent-egress.md`](coding-agent-egress.md), which starts once this zone exists. The host itself is [`coding-agent-host.md`](coding-agent-host.md); putting these rules under Tofu is [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md).

## Scope

The VLAN and subnet, OPNsense interface and rules, the resolver for the zone, and the Tailscale route (advertised by VM 202 and granted to the laptop alone). Not in scope: the egress proxy, its allowlists and the canary probes ([`coding-agent-egress.md`](coding-agent-egress.md)), the host ([`coding-agent-host.md`](coding-agent-host.md)) and OPNsense-as-code ([`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md)).

## Decision

Implements [ADR 0053 (Coding-agent network reach)](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md), `working`, so this project is `de-risking` until its three assumptions are resolved. [`coding-agent-egress.md`](coding-agent-egress.md) names the same revision; it closes last and accepts it.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spikes: filtering proxy feasibility, bridge isolation, resolver design | Not started | The three assumptions in ADR 0053 are resolved and folded into its Context, and the revision can be `approved` |
| 2 | VLAN 60, OPNsense default-deny rules, and the laptop-only Tailscale route, built by hand and documented in a topic doc | Not started | The interface, rules, and route exist and match the topic doc, and the laptop reaches SSH on a scratch VM in the VLAN away from home while another tailnet node cannot |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — spikes

Throwaway, time-boxed, on a scratch VLAN and VM, discarded once answered. The questions: can a host-name-filtering proxy run at acceptable cost; can a guest send tagged frames into another VLAN or reach the node's management address; can the zone's resolver serve no internal zones without breaking address-based access from the maintainer and CD agent.

### Stage 2 — tailnet route

VM 202 advertises the VLAN's route, and the tailnet policy grants it to the laptop on `tcp:22` only, with `tests` asserting that no other node has it. The edit follows the handling in [`operator-host.md`](operator-host.md)'s Stage 2 policy change: copy the current policy first and use the console's preview before saving. Whichever of the two stages edits the policy first replaces the allow-all grant and re-grants everything the maintainer uses today; the other adds its grant. Advertise or approve the route only after the saved policy grants it to the laptop alone, since while allow-all is in force every tailnet node would reach the VLAN.

## Acceptance criteria

- [ ] The VLAN has default-deny in both directions, with only the two source-restricted SSH inbound flows.
- [ ] The rules are described in a topic doc and the topic doc matches an export of the rule set.
- [ ] The zone's subnet is inside no AppRole CIDR binding, and its Tailscale route is granted to the laptop alone.

## Risks

- Hand-maintained rules drift until [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md) lands.
- The route's grant is tailnet policy edited by hand until [ADR 0059 (Tailnet policy)](../decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md) lands, and a wrong edit can expose the VLAN's SSH port to other nodes or lock out access.

## Open items

- Whether the proxy runs on OPNsense or a small dedicated VM (Stage 1); [`coding-agent-egress.md`](coding-agent-egress.md) builds whichever it is.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
