---
id: PROJ-coding-agent-network
title: Coding-Agent Network Zone
type: project
status: de-risking
blocked: false
summary: A dedicated VLAN, default-deny firewall policy, filtering egress proxy, and canary probes for the coding-agent host.
decision: ADR-0053/0
super_project: coding-agent-host
track: boundary
phase: 1-network
---

# Coding-Agent Network Zone

Builds the network boundary the coding-agent host lives behind, before the host exists. Staged because three assumptions in the decision (egress proxy feasibility, bridge isolation, resolver design) must be answered before rules are built on them, and the rules then need an independent check.

The host itself is [`coding-agent-host.md`](coding-agent-host.md); putting these rules under Tofu is [`coding-agent-network-as-code.md`](coding-agent-network-as-code.md).

## Scope

The VLAN and subnet, OPNsense interface and rules, the egress proxy and its allowlist (one proxy, separate allowlists for this VLAN and VLAN 30, [`operator-host.md`](operator-host.md)), the resolver for the zone, the Tailscale route (advertised by VM 202 and granted to the laptop alone), and canary probes. Not in scope: the host ([`coding-agent-host.md`](coding-agent-host.md)) and OPNsense-as-code ([`coding-agent-network-as-code.md`](coding-agent-network-as-code.md)).

## Decision

Implements [ADR 0053 (Coding-agent network reach)](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md), `working`, so this project is `de-risking` until its three assumptions are resolved.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spikes: filtering proxy feasibility, bridge isolation, resolver design | Not started | The three assumptions in ADR 0053 are resolved and folded into its Context, and the revision can be `approved` |
| 2 | VLAN 60, OPNsense default-deny rules, and the laptop-only Tailscale route, built by hand and documented in a topic doc | Not started | The interface, rules, and route exist and match the topic doc, and the laptop reaches SSH on a scratch VM in the VLAN away from home while another tailnet node cannot |
| 3 | Egress proxy with an allowlist derived from what Claude Code and the repo's tooling fetch, ready to take VLAN 30's allowlist | Not started | A canary VM in the VLAN reaches every allowlisted destination and no other |
| 4 | Canary probes from outside the future host | Not started | Probes to the secrets store, CD agent, operator host, managed hosts, workstation, and Proxmox management address all fail |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — spikes

Throwaway, time-boxed, on a scratch VLAN and VM, discarded once answered. The questions: can a host-name-filtering proxy run at acceptable cost; can a guest send tagged frames into another VLAN or reach the node's management address; can the zone's resolver serve no internal zones without breaking address-based access from the maintainer and CD agent.

### Stage 2 — tailnet route

VM 202 advertises the VLAN's route, and the tailnet policy grants it to the laptop on `tcp:22` only, with `tests` asserting that no other node has it. The edit follows the handling in [`operator-host.md`](operator-host.md)'s Stage 2 policy change: copy the current policy first and use the console's preview before saving.

## Acceptance criteria

- [ ] The VLAN has default-deny in both directions, with only the two source-restricted SSH inbound flows.
- [ ] Outbound traffic passes only through the filtering proxy.
- [ ] Canary probes from a VM in the VLAN, run outside the coding-agent host, confirm every prohibited flow fails and every allowlisted destination works.
- [ ] The rules are described in a topic doc and the topic doc matches an export of the rule set.
- [ ] The zone's subnet is inside no AppRole CIDR binding, and its Tailscale route is granted to the laptop alone.

## Risks

- Hand-maintained rules drift until [`coding-agent-network-as-code.md`](coding-agent-network-as-code.md) lands.
- The allowlist needs upkeep as tooling changes.
- The route's grant is tailnet policy edited by hand until [ADR 0059 (Tailnet policy)](../decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md) lands, and a wrong edit can expose the VLAN's SSH port to other nodes or lock out access.
- Docker Hub and other registries sit behind shared CDN addresses; a proxy that filters on host name only may still be broad.

## Open items

- Whether the proxy runs on OPNsense or a small dedicated VM (Stage 1).

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or named by a successor project.
- [ ] The linked revision is `accepted`, another project still names it, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
