---
id: PROJ-tofu-opnsense-day-2
title: OPNsense Day-2 Config via API
type: project
status: de-risking
blocked: false
summary: VLAN interfaces, firewall rules and Kea brought under Tofu through OPNsense's API, then the coding-agent zone and its proxy.
super_project: tofu-vm-provisioning
track: opnsense
---

# OPNsense Day-2 Config via API

Brings OPNsense's day-2 configuration (VLAN interfaces, firewall rules and Kea) under Tofu through its config API, so the hand-built zones stop drifting and the rules that are the network boundary are reviewed as code. It builds on Tofu's root module and credentials file ([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#tofu-project)). It does not wait for [`tofu-migration.md`](tofu-migration.md) or the VMID→IP mapping, which only the DNS records use ([`tofu-vm-dns.md`](tofu-vm-dns.md)).

## Scope

VLAN interfaces, firewall rules and Kea for the existing zones, then the coding-agent zone's interface and rules ([`coding-agent-network.md`](coding-agent-network.md)) and egress-proxy configuration ([`coding-agent-egress.md`](coding-agent-egress.md)), expressed in Tofu, with drift detected against the topic doc. Not in scope: Phase 1 (VM shell and ISO), in [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md), DNS for Tofu-provisioned VMs ([`tofu-vm-dns.md`](tofu-vm-dns.md)), and changing any policy.

## Decision

No decision of its own. Stages 3 to 5 carry out the last bullet of [ADR 0053 (Coding-agent network reach)](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md)'s Decision. It links no `decision:` because that revision becomes `accepted` when the network project completes, while this one is still waiting. If Stage 1 leaves more than one workable provider, the choice is an ADR before Stage 2.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike: which OpenTofu provider manages OPNsense VLAN interfaces, firewall rules and Kea through the API, and how its API key is passed to it | In progress | A provider is chosen against a scratch OPNsense, what it cannot manage is listed here, and the provider takes its API key from the credentials file [ADR 0048 (Tofu credentials)](../decisions/0048-where-tofu-credentials-live/revision-000.md) decides |
| 2 | Import the existing VLAN interfaces, firewall rules and Kea settings. Starts from Tofu's root module and credentials file | Not started | `tofu plan` against OPNsense shows no diff from the hand-built state |
| 3 | The coding-agent zone's interface and rules. Starts once [`coding-agent-network.md`](coding-agent-network.md) has built and documented the zone | Not started | A plan shows no diff from the hand-built zone |
| 4 | The egress proxy's configuration. Starts once [`coding-agent-egress.md`](coding-agent-egress.md) has built the proxy | Not started | The proxy's allowlist is generated from one source in the repo |
| 5 | Retire the hand-maintained state | Not started | The topic doc describes Tofu as the owner of the rules, and canary probes still pass |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] `tofu plan` shows no diff between the code and OPNsense for VLAN interfaces, firewall rules and Kea.
- [ ] The coding-agent zone's interface, rules and proxy configuration are expressed in Tofu, and the canary probes from [`coding-agent-egress.md`](coding-agent-egress.md) still pass after the cut-over.
- [ ] The proxy's allowlist is generated from one source in the repo.
- [ ] The topic doc names Tofu as the owner of the rules.
- [ ] The provider's API key is held in the credentials file ADR 0048 decides.

## Spike notes

Read from the provider's documentation and source, not yet tried against a scratch OPNsense.

- **Candidate.** `browningluke/opnsense` v0.26.0 (MPL-2.0), the only provider found that covers all three areas. It is pre-1.0, its schemas may change between releases, and its own CI runs against OPNsense 26.1.
- **Manages.** `opnsense_interfaces_vlan` (the VLAN device), `opnsense_firewall_filter`, and the Kea DHCPv4 subnet, reservation and peer resources. Each imports by the UUID OPNsense assigns.
- **Cannot manage.** Assigning a VLAN device to an interface and giving that interface its address: the provider has only read-only `interface` data sources for it. Also Kea DDNS and the Kea control agent.
- **API key.** The provider takes `uri`, `api_key` and `api_secret` as arguments or from `OPNSENSE_URI`, `OPNSENSE_API_KEY` and `OPNSENSE_API_SECRET`, and verifies TLS unless `allow_insecure` is set. Variables from the credentials file can fill the arguments.
- **Still to check on a scratch OPNsense.** Whether firewall and Kea changes take effect on apply or need a separate reconfigure, the privileges the API user needs, and that an import of each resource plans clean.

## Risks

- The hand-built rules stay authoritative until Stage 5, and drift until then.
- An import of live rules may show differences the provider cannot express; Stage 1 lists them.
- A plan applied to the live gateway changes live rules, so Stage 2 only plans until one shows no diff.

## Open items

- How each VLAN's interface assignment and gateway address are managed, since the provider has no resource for them. Stage 2's exit condition covers VLAN interfaces, so this settles before Stage 2.
- Whether the proxy's allowlist is generated by Tofu or by Ansible.
- [`vm-provisioning.md`](../topics/infra/vm-provisioning.md)'s OPNsense section ties all of Phase 2 to the VMID→IP mapping. It changes when Stage 2 lands, since DNS records are the only part that needs the mapping.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
