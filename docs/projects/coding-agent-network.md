---
id: PROJ-coding-agent-network
title: Coding-Agent Network Zone
type: project
status: not-started
blocked: false
summary: A dedicated VLAN, default-deny firewall policy and laptop-only Tailscale route for the coding-agent host.
decision: ADR-0053/0
super_project: coding-agent-host
---

# Coding-Agent Network Zone

Builds the zone the coding-agent host lives behind, before the host exists: the VLAN, its default-deny rules and the laptop-only route. Staged because the zone, its route and the gateway's play are separate reviewable changes.

The egress proxy and the canary probes that check the whole boundary are [`coding-agent-egress.md`](coding-agent-egress.md), which starts once this zone exists. The host itself is [`coding-agent-host.md`](coding-agent-host.md); carrying these rules in the gateway's play is this project's last stage, which uses [`opnsense-config.md`](opnsense-config.md)'s role and scratch kit.

## Scope

The VLAN and subnet, OPNsense interface and rules, the resolver for the zone, and the Tailscale route (advertised by VM 202 and granted to the laptop alone). Not in scope: the egress proxy, its allowlists and the canary probes ([`coding-agent-egress.md`](coding-agent-egress.md)), the host ([`coding-agent-host.md`](coding-agent-host.md)) and the gateway's play and rebuild themselves ([`opnsense-config.md`](opnsense-config.md)). The zone's interface and rules in the play are in scope, as Stage 2.

## Decision

Implements [ADR 0053 (Coding-agent network reach)](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md), `working`, so this project is `not-started` or `de-risking` until the revision is `approved`. [`coding-agent-egress.md`](coding-agent-egress.md) names the same revision; it closes last and accepts it.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | VLAN 70, OPNsense default-deny rules, and the laptop-only Tailscale route, built by hand and documented in a topic doc. The route's grant is added as [`tailnet-policy.md`](../topics/infra/tailnet-policy.md#adding-a-grant-for-a-route) describes | Not started | The interface, rules, and route exist and match the topic doc, and the laptop reaches SSH on a scratch VM in the VLAN away from home while another tailnet node cannot |
| 2 | Carry the zone in the gateway's play: VLAN 70 in the seed's VLAN list and the role's zones, and rows 8 and 13 of [`opnsense-config.md`](opnsense-config.md)'s flow list. Starts once the zone is documented | Not started | `--check --diff` reports no change on a scratch gateway, the zone's flows in the flow list pass, and nothing else is denied that was allowed |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — tailnet route

VM 202 advertises the VLAN's route, and the tailnet policy grants it to the laptop on `tcp:22` only, with `tests` asserting that no other node has it. This stage only adds its grant to the policy's explicit grants, as [`operator-host.md`](operator-host.md)'s Stage 1 does: copy the current policy first and use the console's preview before saving. Advertise or approve the route only after the saved policy grants it to the laptop alone.

## Acceptance criteria

- [ ] The VLAN has default-deny in both directions, with only the two source-restricted SSH inbound flows.
- [ ] The rules are described in a topic doc and the topic doc matches an export of the rule set.
- [ ] The zone's interface and rules are expressed in the gateway's play and the scratch gateway's acceptance run passes with them.
- [ ] The zone's subnet is inside no AppRole CIDR binding, and its Tailscale route is granted to the laptop alone.

## Risks

- Hand-maintained rules drift until the production gateway is rebuilt from the play ([`opnsense-config.md`](opnsense-config.md)'s last stage). A zone built by hand before that rebuild must be in the play by then.
- The route's grant is tailnet policy edited by hand until [ADR 0059 (Tailnet policy)](../decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md) lands, and a wrong edit can expose the VLAN's SSH port to other nodes or lock out access.

## Open items

- Whether the proxy runs on OPNsense or a small dedicated VM (decided under ADR 0053); [`coding-agent-egress.md`](coding-agent-egress.md) builds whichever it is.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
