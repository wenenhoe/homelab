---
id: PROJ-coding-agent-network
title: Coding-Agent Network Zone
type: project
status: building
blocked: false
summary: A dedicated VLAN, default-deny firewall policy and laptop-only Tailscale route for the coding-agent host.
decision: ADR-0053/1
super_project: coding-agent-host
allowed_paths:
  - docs/topics/infra/coding-agent-network.md
  - docs/topics/infra/tailnet-policy.md
  - docs/topics/infra/network-boundary-checks.md
  - docs/topics/infra/scratch-gateway-runs.md
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

Builds the zone the coding-agent host lives behind, before the host exists: the VLAN, its default-deny rules and the laptop-only route. Staged because the zone, its route and the gateway's play are separate reviewable changes.

The egress proxy and the canary probes that check the whole boundary are [`coding-agent-egress.md`](coding-agent-egress.md), which starts once this zone exists. The host itself is [`coding-agent-host.md`](coding-agent-host.md); carrying these rules in the gateway's play is this project's last stage, which uses [`opnsense-config.md`](opnsense-config.md)'s role and scratch kit.

## Scope

The VLAN and subnet, OPNsense interface and rules, and the Tailscale route (advertised by VM 202 and granted to the laptop alone). Not in scope: the egress proxy, its allowlists, the zone's resolver and the canary probes ([`coding-agent-egress.md`](coding-agent-egress.md)), the host ([`coding-agent-host.md`](coding-agent-host.md)) and the gateway's play and rebuild themselves ([`opnsense-config.md`](opnsense-config.md)). The zone's interface and rules in the play are in scope, as Stage 2.

Not in: `tofu/tests/proxmox_ubuntu_vm.tftest.hcl` and `tools/tests/scratch_run/test_run_canary_vm.py`, which use VLAN 30 and VMID 302 as an example of the VMID scheme and are unaffected by the zone's rules.

## Decision

Implements [ADR 0053 revision 1 (Coding-agent network reach)](../decisions/0053-network-reach-of-the-coding-agent-host/revision-001.md), and builds only while that revision is `approved`. The proxy the zone reaches the Internet through is [ADR 0116 (Egress for default-deny zones)](../decisions/0116-internet-egress-for-hosts-in-default-deny-zones/revision-000.md), built by [`coding-agent-egress.md`](coding-agent-egress.md), which names this revision in `also_implements:`; it closes last and accepts it.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | VLAN 30, OPNsense default-deny rules, and the laptop-only Tailscale route, built by hand and documented in a topic doc. The seed already carries the VLAN as `opt3` ([`opnsense-config.md`](opnsense-config.md#hand-offs)), so the interface the hand-built zone gets on the live gateway does not bind Stage 2: the play is not applied to the live gateway, and the rebuild creates the interface from the seed. The route's grant is added as [`tailnet-policy.md`](../topics/infra/tailnet-policy.md#adding-a-grant-for-a-route) describes | In progress | The interface, rules, and route exist and match the topic doc, and the laptop reaches SSH on a scratch VM in the VLAN away from home while another tailnet node cannot |
| 2 | Carry the zone in the gateway's play: VLAN 30 in the role's zones as `opt3`, which the seed already gives it, and rows 7 and 12 of [`opnsense-config.md`](opnsense-config.md)'s flow list. The `seed-vlans` run (the `vlan-30-seed` run under its earlier name) builds a gateway with the seed's own VLANs and stays as it is; the zone's steps go in a run of its own, as the DMZ's went in `dmz-probe`, and its canary and flows go in the flow list as the DMZ's did. The zone's outbound rule to the proxy and resolver in VLAN 45 is added with that zone by [`coding-agent-egress.md`](coding-agent-egress.md). Starts once the zone is documented | Not started | `--check --diff` reports no change on a scratch gateway, the zone's flows in the flow list pass, and nothing else is denied that was allowed |

Stage status is `Not started`, `In progress`, or `Done`.

Until Stage 2 lands, these are untested: a VM tagged 30 reaching the gateway, the zone's flows (rows 7 and 12) and default-deny inside VLAN 30. The scratch kit shows only that a scratch gateway built with the seed's VLANs has VLAN 30's interface (the `seed-vlans` run); [`scratch-gateway-runs.md`](../topics/infra/scratch-gateway-runs.md#untested-until-vlan-30-has-a-zone) says what each remaining check needs. Stage 2's exit condition is the first run of a `canary-vm`-style spec for the new zone.

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

None.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
