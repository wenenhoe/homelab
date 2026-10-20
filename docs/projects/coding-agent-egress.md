---
id: PROJ-coding-agent-egress
title: Coding-Agent Egress Proxy and Canary Probes
type: project
status: not-started
blocked: false
summary: A filtering egress proxy for the coding-agent zone and VLAN 30, and canary probes that check the whole boundary from outside the host.
decision: ADR-0053/0
super_project: coding-agent-host
track: egress
depends_on:
  - project: PROJ-coding-agent-network
    reason: the proxy sits in a zone that already exists, and its design is settled by that project's spikes
---

# Coding-Agent Egress Proxy and Canary Probes

Builds the only way out of the coding-agent zone, and the independent check that the boundary holds. The zone itself (VLAN, default-deny rules, laptop-only route) is [`coding-agent-network.md`](coding-agent-network.md); this project starts once it exists. It is separate because the host needs the zone before it needs a way out, and because [`operator-host-takeover.md`](operator-host-takeover.md) needs the proxy for VLAN 30 without needing anything else from the zone.

## Scope

The egress proxy and its allowlists (one proxy, separate allowlists for the coding-agent VLAN and VLAN 30), and canary probes run from a VM in the zone, outside the host. Not in scope: the VLAN, rules and route ([`coding-agent-network.md`](coding-agent-network.md)), the host ([`coding-agent-host.md`](coding-agent-host.md)), and putting the proxy's configuration under Tofu ([`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md)).

## Decision

Implements [ADR 0053 (Coding-agent network reach)](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md), `working`, so this project is `not-started` until [`coding-agent-network.md`](coding-agent-network.md)'s spikes resolve its assumptions and the revision is `approved`. This is the last project to name the revision, so it accepts it when it closes.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Egress proxy with an allowlist derived from what Claude Code and the repo's tooling fetch, ready to take VLAN 30's allowlist | Not started | A canary VM in the VLAN reaches every allowlisted destination and no other |
| 2 | Canary probes from outside the future host | Not started | Probes to the secrets store, CD agent, operator host, managed hosts, workstation, and Proxmox management address all fail |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] Outbound traffic from the zone passes only through the filtering proxy.
- [ ] Canary probes from a VM in the VLAN, run outside the coding-agent host, confirm every prohibited flow fails and every allowlisted destination works.
- [ ] The proxy and its allowlists are described in the topic doc [`coding-agent-network.md`](coding-agent-network.md) writes, and that doc matches an export of the rule set.

## Risks

- The allowlist needs upkeep as tooling changes.
- Docker Hub and other registries sit behind shared CDN addresses; a proxy that filters on host name only may still be broad.
- Hand-maintained proxy configuration drifts until [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md) lands.

## Open items

- Where the proxy runs, OPNsense or a small dedicated VM, is answered by [`coding-agent-network.md`](coding-agent-network.md)'s Stage 1; this project builds whichever it is.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
