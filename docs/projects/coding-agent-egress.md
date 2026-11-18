---
id: PROJ-coding-agent-egress
title: Egress Proxies and Canary Probes
type: project
status: not-started
blocked: false
summary: The two filtering forward proxies in VLAN 45 that give the management, coding-agent and DMZ zones their only way to the Internet, the per-VM address filter that keys them, and canary probes that check the coding-agent boundary from outside the host.
decision: ADR-0116/0
also_implements: [ADR-0053/1]
plan: draft
super_project: coding-agent-host
depends_on:
  - project: PROJ-coding-agent-network
    reason: the canary probes run from a VM in the coding-agent zone, and the untrusted tier's resolver serves it
---

# Egress Proxies and Canary Probes

Builds the only way out of the zones that deny direct Internet access, and the independent check that the coding-agent boundary holds. The coding-agent zone itself (VLAN, default-deny rules, laptop-only route) is [`coding-agent-network.md`](coding-agent-network.md). The proxies serve more than that zone, so they are not part of it: [`operator-host-takeover.md`](operator-host-takeover.md) needs the trusted tier for VLAN 25 without needing anything else from the coding-agent zone, and [`gatehouse.md`](gatehouse.md) needs the untrusted tier for the DMZ.

## Scope

VLAN 45 and its interface rules, the trusted-tier and untrusted-tier proxy VMs with their allowlists, the coding-agent zone's resolver on the untrusted tier's VM, the per-VM IP filter that each consumer carries, the temporary rule that admits the operator host directly when the trusted tier is down, and canary probes run from a VM in the coding-agent zone, outside the host. Not in scope: the coding-agent zone's VLAN, rules and route ([`coding-agent-network.md`](coding-agent-network.md)), the hosts that use a proxy ([`coding-agent-host.md`](coding-agent-host.md), [`operator-host-takeover.md`](operator-host-takeover.md), [`gatehouse.md`](gatehouse.md)), and the gateway's play and rebuild themselves ([`opnsense-config.md`](opnsense-config.md)). The zone's and the proxies' configuration in the play is in scope, as Stages 3 and 5.

## Decision

Implements [ADR 0116 (Egress for default-deny zones)](../decisions/0116-internet-egress-for-hosts-in-default-deny-zones/revision-000.md), `approved`, which gates this project. It also carries out [ADR 0053 revision 1 (Coding-agent network reach)](../decisions/0053-network-reach-of-the-coding-agent-host/revision-001.md), `approved`, named in `also_implements:`: the coding-agent zone's outbound path and resolver are the untrusted tier and its VM. [`coding-agent-network.md`](coding-agent-network.md) builds that revision's zone and this project closes last, so it accepts that revision when it closes. Closing needs both revisions `accepted`, or named by a project that remains.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | VLAN 45 and the two proxy VMs, built by hand on the gateway and by Tofu and Ansible on the VMs. The trusted tier carries the management zone's allowlist of named hosts, the untrusted tier the coding-agent zone's allowlist derived from what Claude Code and the repo's tooling fetch plus the Tailscale domain for the DMZ, and its VM carries the resolver with no internal zone | Not started | A canary VM at a consumer's address reaches every destination its own tier allows and no other, an address that is no tier's consumer is refused by both, and an internal name does not resolve through the zone's resolver while a public one does |
| 2 | Canary probes from outside the future host | Not started | Probes to the secrets store, CD agent, operator host, managed hosts, workstation, and Proxmox management address all fail, and the allowlisted destinations work |
| 3 | Carry the zone and the allowlists in the play: VLAN 45 in the seed's VLAN list and the role's zones, and the allowlists generated from one source in the repo. Starts once the proxies exist | Not started | The allowlists are generated from one source, `--check --diff` reports no change on a scratch gateway, and the canary probes still pass |
| 4 | The per-VM IP filter in the consumer VMs' Tofu, each with its own address, with the node's datacenter firewall on | Not started | A scratch VM that sends as another consumer's IPv4 address is dropped, and a proxy keys on the address it sees |
| 5 | The temporary rule for a down trusted tier, switched by a variable in the play | Not started | Applying it admits the operator host to the state backend's and the providers' endpoints, removing it restores the deny, and a rule left in place is reported by `--check` as a changed task named for the rule |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] Outbound traffic from each of the three zones passes only through the proxy of its own tier, and each consumer is admitted only to its own allowlist.
- [ ] Canary probes from a VM in the coding-agent zone, run outside the coding-agent host, confirm every prohibited flow fails and every allowlisted destination works.
- [ ] The allowlists are generated from one source in the repo and applied by code, and the canary probes still pass after the production gateway is rebuilt.
- [ ] The proxies and their allowlists are described in the topic doc [`coding-agent-network.md`](coding-agent-network.md) writes, and that doc matches an export of the rule set.

## Risks

- The allowlists need upkeep as tooling changes, and a change to the trusted tier's is a security-relevant change to review.
- Docker Hub and other registries sit behind shared CDN addresses; a proxy that filters on host name only may still be broad.
- A trusted-tier outage blocks Tofu until the VM is rebuilt or the temporary rule is applied.
- Hand-maintained zone and proxy configuration drifts until the production gateway is rebuilt from the play ([`opnsense-config.md`](opnsense-config.md)'s last stage).

## Open items

- Sizing reviewed against ADR 0037 revision 5: kept apart from `coding-agent-network.md`, which it depends on, since the zone is gateway configuration and the proxies are services on VMs. The project now holds two tiers, the address filter and the temporary rule, so Stage 1 splits per tier if it proves too large for one PR.
- Whether the operator host and the CD agent run hooks or builds that pull from a container registry. If they do, the trusted tier's allowlist needs that registry, and a registry behind a shared CDN is the broad case in the risks.
- Whether the allowlists are generated by the gateway's play or by their own role, which depends on where the proxy configuration is applied from.
- Whether [`operator-host-takeover.md`](operator-host-takeover.md) and [`gatehouse.md`](gatehouse.md) name ADR 0116 in `also_implements:`, so it is not accepted before its trusted tier and its DMZ consumer exist. Settled when the first of them is planned against it.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
