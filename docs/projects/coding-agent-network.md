---
id: PROJ-coding-agent-network
title: Coding-Agent Network Zone
type: project
status: building
blocked: false
summary: A dedicated VLAN, default-deny firewall policy and laptop-only Tailscale route for the coding-agent host.
decision: ADR-0053/0
super_project: coding-agent-host
allowed_paths:
  - docs/decisions/0053-network-reach-of-the-coding-agent-host/**
  - docs/topics/infra/coding-agent-network.md
  - docs/topics/infra/tailnet-policy.md
  - docs/topics/infra/network-boundary-checks.md
  - docs/topics/infra/scratch-gateway-runs.md
  - docs/topics/infra/tofu/opnsense-gateway.md
  - docs/topics/infra/tofu/opnsense-scratch-gateway.md
  - docs/topics/infra/tofu/ubuntu-vms.md
  - ansible/roles/opnsense_gateway/**
  - ansible/tests/test_opnsense_*.py
  - tofu/scratch/opnsense/runs/**
  - tools/network_checks/flows.yaml
  - tools/tests/scratch_run/test_run_cli.py
  - .github/workflows/scratch-gateway-qemu.yml
sweep_terms:
  - vlan-30-seed
  - Untested until VLAN 30
---

# Coding-Agent Network Zone

Builds the zone the coding-agent host lives behind, before the host exists: the VLAN, its default-deny rules and the laptop-only route. Staged because the zone in the gateway's play, and its application to the production gateway with the route, are separate reviewable changes.

The egress proxy and the canary probes that check the whole boundary are [`coding-agent-egress.md`](coding-agent-egress.md), which starts once this zone exists. The host itself is [`coding-agent-host.md`](coding-agent-host.md); carrying these rules in the gateway's play is this project's first stage, which uses the gateway's role and scratch kit ([`opnsense-gateway.md`](../topics/infra/tofu/opnsense-gateway.md)).

## Scope

The VLAN and subnet, OPNsense interface and rules, and the Tailscale route (advertised by VM 202 and granted to the laptop alone). Not in scope: the egress proxy, its allowlists, the zone's resolver and the canary probes ([`coding-agent-egress.md`](coding-agent-egress.md)), the host ([`coding-agent-host.md`](coding-agent-host.md)) and the gateway's play and rebuild themselves ([`opnsense-gateway.md`](../topics/infra/tofu/opnsense-gateway.md)). The zone's interface and rules in the play are in scope, as Stage 1.

Not in: `tofu/tests/proxmox_ubuntu_vm.tftest.hcl` and `tools/tests/scratch_run/test_run_canary_vm.py`, which use VLAN 30 and VMID 302 as an example of the VMID scheme and are unaffected by the zone's rules.

## Decision

Implements [ADR 0053 (Coding-agent network reach)](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md), and builds only while that revision is `approved`. The proxy the zone reaches the Internet through is [ADR 0116 (Egress for default-deny zones)](../decisions/0116-internet-egress-for-hosts-in-default-deny-zones/revision-000.md), built by [`coding-agent-egress.md`](coding-agent-egress.md), which names this revision in `also_implements:`; it closes last and accepts it.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Carry the zone in the gateway's play: VLAN 30 in the role's zones as `opt4`, which the seed already gives it, and the [`operator-vlan30-ssh`](../topics/infra/tofu/opnsense-gateway.md#zone-policy) and [`tailscale-vlan30-ssh`](../topics/infra/tofu/opnsense-gateway.md#zone-policy) flows of the zone policy. The `seed-vlans` run (the `vlan-30-seed` run under its earlier name) builds a gateway with the seed's own VLANs and stays as it is; the zone's steps go in a run of its own, as the DMZ's went in `dmz-probe`, and its canary and flows go in the flow list as the DMZ's did. The zone's outbound rule to the proxy and resolver in VLAN 45 is added with that zone by [`coding-agent-egress.md`](coding-agent-egress.md). The zone is written in the play and rehearsed on a scratch gateway, and is not built by hand on the live gateway | In progress | `--check --diff` reports no change on a scratch gateway, the zone's flows in the flow list pass, and nothing else is denied that was allowed |
| 2 | Apply the zone to the production gateway and add the laptop-only Tailscale route. The production gateway is built from the seed and the play, so the interface is the seed's `opt4`. The route's grant is added as [`tailnet-policy.md`](../topics/infra/tailnet-policy.md#adding-a-grant-for-a-route) describes | Not started | `--check --diff` reports no change on the production gateway, the zone's flows pass from its canary, the interface, rules and route match the topic doc, and the laptop reaches SSH on a scratch VM in the VLAN away from home while another tailnet node cannot |

Stage status is `Not started`, `In progress`, or `Done`.

The play carries the zone, its [`operator-vlan30-ssh`](../topics/infra/tofu/opnsense-gateway.md#zone-policy) and [`tailscale-vlan30-ssh`](../topics/infra/tofu/opnsense-gateway.md#zone-policy) flows and the zone's flows in the flow list, and [`coding-zone`](../topics/infra/scratch-gateway-runs.md#the-coding-agent-zone-run) is the run that shows them from a VM tagged 30. Stage 1 is done when that run's first pass has `--check --diff` reporting no change and every one of its steps passing; no other run shows a VM tagged 30 reaching the gateway or default-deny inside VLAN 30.

## Where things sit

- **Merged for Stage 1:** the zone in the gateway's play (VLAN 30 as `opt3` on the gateway as it was then built and `opt4` from the current seed, no Internet, no DHCP, and the gateway's DNS withheld from it through the zone's `gateway_dns: false`), the two SSH flows into the host's address, the zone's flows in the flow list, and the `coding-zone` run spec with its tests. The play has been applied to the production gateway with the zone in it and a second `--check --diff` reported no change. The tailnet route has not been added and no flow has been run from the zone's canary.
- **Whether the host uses the zone:** where the host runs, on the node in this VLAN or on a cloud instance, is an open exploration. If it leaves the node, the zone has no host to protect and Stage 2 (applying the zone and the tailnet route) is not worth doing for it. The zone and its flows then stay in the play and the flow list as a restrictive zone the node can place a VM in later, and this project closes at Stage 1 with the closing checklist deciding what is kept.
- **Stage 2** therefore waits on the host-placement question, and starts only if the host stays on the node.

### Stage 2 — tailnet route

VM 202 advertises the VLAN's route, and the tailnet policy grants it to the laptop on `tcp:22` only, with `tests` asserting that no other node has it. This stage only adds its grant to the policy's explicit grants, as [`operator-host.md`](operator-host.md)'s Stage 1 does: copy the current policy first and use the console's preview before saving. Advertise or approve the route only after the saved policy grants it to the laptop alone.

## Acceptance criteria

- [ ] The VLAN has default-deny in both directions, with only the two source-restricted SSH inbound flows.
- [ ] The rules are described in a topic doc and the topic doc matches an export of the rule set.
- [ ] The zone's interface and rules are expressed in the gateway's play and the scratch gateway's acceptance run passes with them.
- [ ] The zone's subnet is inside no AppRole CIDR binding, and its Tailscale route is granted to the laptop alone.

## Risks

- The zone's rules reach the production gateway only through its play ([`opnsense-gateway.md`](../topics/infra/tofu/opnsense-gateway.md)). They are never built by hand on the live gateway.
- The route's grant is tailnet policy edited by hand until [ADR 0059 (Tailnet policy)](../decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md) lands, and a wrong edit can expose the VLAN's SSH port to other nodes or lock out access.

## Open items

- Whether the host runs on the node or on a cloud instance, an open exploration, which decides whether Stage 2 is built.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
