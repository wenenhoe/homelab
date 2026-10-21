---
id: PROJ-tofu-opnsense-day-2
title: OPNsense Day-2 Config via API
type: project
status: de-risking
blocked: false
summary: The OPNsense gateway's policy, NAT, DNS forwards and DHCP brought under Ansible through its API from a minimal seed, then the coding-agent zone and its proxy.
decision: ADR-0089/0
super_project: tofu-vm-provisioning
track: opnsense
---

# OPNsense Day-2 Config via API

Brings the OPNsense gateway's configuration under code, so the rules that are the network boundary are reviewed as code and the gateway can be rebuilt from nothing. A minimal seed that Tofu attaches sets what the API cannot, and the Ansible collection applies the rest ([ADR 0089 (OPNsense configuration)](../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md)). It builds on Tofu's root module and credentials file ([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#tofu-project)). Only its last stage waits for [`tofu-migration.md`](tofu-migration.md); the rest runs on a scratch gateway in that project's isolated block. DNS records for Tofu-provisioned VMs are [`tofu-vm-dns.md`](tofu-vm-dns.md)'s.

## Scope

The seed image and its attachment to the OPNsense module, the Ansible role that applies the gateway's configuration, and the policy, NAT, Unbound forwards and Kea scratch network it holds for the existing zones. Then the coding-agent zone's interface and rules ([`coding-agent-network.md`](coding-agent-network.md)) and egress-proxy configuration ([`coding-agent-egress.md`](coding-agent-egress.md)), with drift detected by the play's check. Not in scope: Phase 1 (VM shell and ISO), in [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md), DNS for Tofu-provisioned VMs ([`tofu-vm-dns.md`](tofu-vm-dns.md)), and changing any policy the other decisions set.

## Decision

Implements [ADR 0089 (OPNsense configuration)](../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md), still `working`, so this project is `de-risking` until that revision's open assumptions are resolved. Stages 4 and 5 also carry out the last bullet of [ADR 0053 (Coding-agent network reach)](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md)'s Decision, which becomes `accepted` when the network project completes.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike on a scratch OPNsense in the isolated block: the seed's first-boot import, the API user and its key, the collection's coverage, savepoint revert, the gateway certificate, Unbound forwards | In progress | Each assumption in ADR 0089 is resolved and folded into its Context, and the revision can be `approved` |
| 2 | The seed image and the Ansible role's skeleton. Starts from Tofu's root module and credentials file | Not started | A scratch gateway builds from the seed, and the play's `--check --diff` reports no change after it converges |
| 3 | Policy, NAT, Unbound forwards and the Kea scratch network for the existing zones, with the hardening baseline | Not started | `--check --diff` reports no change, and probes from a canary VM confirm the allowed flows work and the others fail |
| 4 | The coding-agent zone's interface and rules. Starts once [`coding-agent-network.md`](coding-agent-network.md) has built and documented the zone | Not started | `--check --diff` reports no change, and the zone's canary probes pass |
| 5 | The egress proxy's configuration. Starts once [`coding-agent-egress.md`](coding-agent-egress.md) has built the proxy | Not started | The proxy's allowlist is generated from one source in the repo |
| 6 | Rebuild the production gateway from the seed and apply the play, with [`tofu-migration.md`](tofu-migration.md)'s cutover. Retire the hand-maintained state | Not started | The topic doc describes the repo as the owner of the gateway's configuration, and canary probes still pass |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] A scratch gateway builds from the seed, and the play's `--check --diff` reports no change once it has converged.
- [ ] The policy, NAT, Unbound forwards and Kea scratch network for the existing zones are expressed in the play, and canary probes confirm every allowed flow works and every other fails.
- [ ] The coding-agent zone's interface, rules and proxy configuration are expressed in the play, and the canary probes from [`coding-agent-egress.md`](coding-agent-egress.md) still pass after the cutover.
- [ ] The proxy's allowlist is generated from one source in the repo.
- [ ] The production gateway is rebuilt from the seed, and the topic doc names the repo as the owner of its configuration.
- [ ] The API credential is held only in the credentials file ADR 0048 decides.

## Risks

- The hand-built rules stay authoritative until Stage 6, and drift until then.
- The collection works only with the OPNsense release of the same version, so the gateway's release waits for the collection's.
- A play applied to the live gateway changes live rules, so it runs with `--check --diff` first and applies firewall changes under a savepoint.

## Open items

- Whether the proxy's allowlist is generated by the gateway's play or by its own role, which depends on where the proxy runs ([`coding-agent-network.md`](coding-agent-network.md)'s Stage 1).
- [`vm-provisioning.md`](../topics/infra/vm-provisioning.md)'s OPNsense section ties all of Phase 2 to the VMID→IP mapping. It changes when Stage 2 lands, since DNS records are the only part that needs the mapping.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
