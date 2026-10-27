---
id: PROJ-opnsense-config
title: OPNsense Gateway Configuration
type: project
status: building
blocked: false
summary: The OPNsense gateway's policy, NAT, DNS forwards and DHCP brought under Ansible through its API from a minimal seed, then the coding-agent zone and its proxy.
decision: ADR-0089/0
super_project: tofu-vm-provisioning
track: opnsense
---

# OPNsense Gateway Configuration

Brings the OPNsense gateway's configuration under code, so the rules that are the network boundary are reviewed as code and the gateway can be rebuilt from nothing. A minimal seed that Tofu attaches sets what the API cannot, and the Ansible collection applies the rest ([ADR 0089 (OPNsense configuration)](../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md)). It builds on Tofu's root module and credentials file ([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#tofu-project)). Only its last stage waits for [`tofu-migration.md`](tofu-migration.md); the rest runs on a scratch gateway in that project's isolated block. DNS records for Tofu-provisioned VMs come from the `bind9` role ([`bind9.md`](../topics/services/bind9.md#the-host-zone)).

## Scope

The seed image and its attachment to the OPNsense module, the Ansible role that applies the gateway's configuration, and the policy, NAT, Unbound forwards and Kea scratch network it holds for the existing zones. Then the coding-agent zone's interface and rules ([`coding-agent-network.md`](coding-agent-network.md)) and egress-proxy configuration ([`coding-agent-egress.md`](coding-agent-egress.md)), with drift detected by the play's check. Not in scope: Phase 1 (VM shell and ISO), in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md#opnsense), DNS for Tofu-provisioned VMs ([`bind9.md`](../topics/services/bind9.md#the-host-zone)), and changing any policy the other decisions set.

## Decision

Implements [ADR 0089 (OPNsense configuration)](../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md), `approved` once its assumptions were resolved. Stages 4 and 5 also carry out the last bullet of [ADR 0053 (Coding-agent network reach)](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md)'s Decision, which becomes `accepted` when the network project completes.

The pinned pair is OPNsense 26.1.11 and the `oxlorg.opnsense` collection at commit `5cec92ea25c8280a9913dfb958109f78ce930d00`, whose `galaxy.yml` reads version 26.1.11. The collection's git tag `26.1.11` carries an earlier version's metadata, so the pin is the commit. The pair lives in the `opnsense_gateway` role's defaults, and `ansible/requirements.yml` installs the collection from git at the same commit. The mirror reports the 26.1 series as end of life, and 26.1.11 is its last release. The pair stays there: a move to 26.7 with a matching collection release is a release change, rehearsed on a scratch clone as the ADR's Validation describes, after the policy is written.

The seed builder and the script that answers the importer at the first boot are in the module's directory ([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#opnsense)). The scratch gateway is built by a spike kit kept out of the repo, which applies the OPNsense module with Tofu from a workstation and runs the update and package checks. Its LAN NIC attaches to an isolated bridge with no physical port (the spike used `vmbr9`, since removed with its Proxmox permissions; a new run creates one and grants the token `SDN.Use` on it), because the seed's LAN serves DHCP and must not share a bridge with real ports; the kit refuses a LAN bridge that has one. Its WAN NIC attaches untagged to `vmbr1`, where the production gateway's DHCP gives it an address and a route out. Do not give a scratch gateway the production WAN bridge.

A gateway built from the 26.1.6 `nano` image updated through its own API to 26.1.11 (core 26.1.11_10) in one update with one reboot. Afterwards the seeded API key still authenticated and a wrong secret was still refused, over the pinned certificate; the serial console showed a login prompt; and a package that was not installed installed and removed. The API's `product_latest` listing said 26.1.7 while the repository held 26.1.11, so the update list, not that listing, says where an update lands. A gateway that is behind its repository refuses a package install, so the update comes first. The live `config.xml` is not readable through the API (the backup download serves the newest saved backup), so no before and after hash of it was taken.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike on a scratch OPNsense in the isolated block: the seed's first-boot import, the API user and its key, the collection's coverage, savepoint revert, the gateway certificate, Unbound forwards, the unattended install | Done | Each assumption in ADR 0089 is resolved and folded into its Context, and the revision can be `approved` |
| 2 | The seed image and the Ansible role's skeleton. Starts from Tofu's root module and credentials file | In progress | A scratch gateway builds from the seed, and the play's `--check --diff` reports no change after it converges |
| 3 | Policy, NAT, Unbound forwards and the Kea scratch network for the existing zones, with the hardening baseline | Not started | `--check --diff` reports no change, and the flow list's probes ([`network-boundary-checks.md`](network-boundary-checks.md)) confirm the allowed flows work and the others fail |
| 4 | The coding-agent zone's interface and rules. Starts once [`coding-agent-network.md`](coding-agent-network.md) has built and documented the zone | Not started | `--check --diff` reports no change, and the zone's flows in the flow list pass |
| 5 | The egress proxy's configuration. Starts once [`coding-agent-egress.md`](coding-agent-egress.md) has built the proxy | Not started | The proxy's allowlist is generated from one source in the repo |
| 6 | Rebuild the production gateway (VM 201) from the seed and apply the play, after [`tofu-migration.md`](tofu-migration.md)'s cutover of the Ubuntu hosts. Retire the hand-maintained state and decommission the old VM | Not started | The topic doc describes the repo as the owner of the gateway's configuration, the old VM is decommissioned, and canary probes still pass |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] A scratch gateway builds from the seed, and the play's `--check --diff` reports no change once it has converged.
- [ ] The policy, NAT, Unbound forwards and Kea scratch network for the existing zones are expressed in the play, and the flow list's probes confirm every allowed flow works and every other fails.
- [ ] The coding-agent zone's interface, rules and proxy configuration are expressed in the play, and the canary probes from [`coding-agent-egress.md`](coding-agent-egress.md) still pass after the cutover.
- [ ] The proxy's allowlist is generated from one source in the repo.
- [ ] The production gateway is rebuilt from the seed, the old VM is decommissioned, and the topic doc names the repo as the owner of its configuration.
- [ ] The API credential is held only in the credentials file ADR 0048 decides.

## Risks

- The hand-built rules stay authoritative until Stage 6, and drift until then.
- The collection works only with the OPNsense release of the same version, so the gateway's release waits for the collection's.
- The pinned series no longer gets fixes once it is end of life, so the move to 26.7 is a later release change, not an option to skip.
- A play applied to the live gateway changes live rules, so it runs with `--check --diff` first and the gateway VM is snapshotted before each apply.

## Open items

- Whether the proxy's allowlist is generated by the gateway's play or by its own role, which depends on where the proxy runs ([`coding-agent-network.md`](coding-agent-network.md)'s Stage 1).
- [`vm-provisioning.md`](../topics/infra/vm-provisioning.md)'s OPNsense section ties all of Phase 2 to the VMID→IP mapping. It changes when Stage 2 lands, since DNS records are the only part that needs the mapping.
- The live gateway (VM 201) is an `i440fx` machine with SeaBIOS and an 8 GB disk, while the OPNsense module builds `q35`. Settle which the rebuilt gateway uses before Stage 6.
- How the operator host resolves the management name. The play checks that it does, and a renewal of the certificate (every 397 days) is noticed by the play's failed authentication.
- Whether [ADR 0048 (Tofu credentials)](../decisions/0048-where-tofu-credentials-live/revision-000.md) needs a revision, now that the play reads the OPNsense API key and secret from its credentials file, and that the CD agent's toolchain installs a collection from git.
- Connections from the workstation to the Proxmox API dropped now and then during spike runs (an upload closed mid-transfer, a VM create answered with an empty reply). A retried apply then succeeded. The cause is not found, and the module has no retry of its own.
- Which credential takes the snapshot [ADR 0089 (OPNsense configuration)](../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md) requires before each apply. The Proxmox token in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md#proxmox-api-token) holds no snapshot privilege. The leading option is a token of its own, scoped to the gateway VM, that can create and delete snapshots but not roll back, kept with the play's other credentials in the file ADR 0048 decides because the play runs when OpenBao may be unreachable behind the gateway it changes. A rollback stays a person's act, and a CD agent job could hold the token later.
- How a clean `--check --diff` is judged. The exit conditions of Stages 2 to 4 say a converged gateway reports no change, but ADR 0089's Context lists objects whose report is never clean: package locks, anything set through the generic call, a user password set to `always`, extra lines in alias and user diffs, and a forward reported changed with no diff. The settings only the seed sets are never reported at all. Options are an allow-list of the known noise, a comparison of the downloaded configuration against the seed for the seed-only settings, or leaving those objects out of the check. Settle it before Stage 3, and keep each module's raw output from a clean run, a run after a GUI change and a second converge as test fixtures in Stage 2, so the choice rests on real output.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
