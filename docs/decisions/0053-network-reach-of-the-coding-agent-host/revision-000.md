---
id: ADR-0053
revision: 0
type: adr
title: Network reach of the coding-agent host
solution: Its own VLAN, default-deny both ways at OPNsense, egress through a domain-filtering proxy, and a resolver with no internal zones
summary: What the coding-agent host can reach and be reached from, enforced at the firewall rather than on the host.
topic: security-hardening
status: working
related: [ADR-0020, ADR-0039, ADR-0040]
---

# 0053. Network reach of the coding-agent host

## Problem

A compromised agent session on the coding-agent host has no network path to the secrets store, the CD agent, the managed hosts, the Proxmox node, or the maintainer's workstation. The boundary is enforced outside the host, so it holds whatever runs on it.

## Context

[`vm-provisioning.md`](../../vm-provisioning.md) maps each VMID-hundred range to a VLAN by `vlan_id = (vmid // 100) * 10`, with `.1` reserved for OPNsense's sub-interface. The 6XX–8XX ranges are unassigned. Every VM attaches to one VLAN-aware bridge on the node.

[ADR 0020](../0020-automation-identity-and-access-scope/revision-001.md) binds AppRoles by source CIDR, so subnet boundaries are also an authentication factor. OPNsense rules are hand-maintained today; the Tofu project that would manage them ([`tofu-opnsense-day-2.md`](../../projects/tofu-opnsense-day-2.md)) waits behind the migration.

Claude Code needs `api.anthropic.com`, `claude.ai` and `platform.claude.com` for sign-in and token refresh, and `downloads.claude.ai` for its native installer and updater. The repo's own tooling fetches from PyPI, Ansible Galaxy, GitHub, `ghcr.io`, Docker Hub, and Ubuntu mirrors.

**Threat model.** The adversary is a compromised agent session. The assets are the secrets store, the CD agent, and hosts reachable from it. An allowlist limits lateral reach and drive-by fetches. It cannot stop the agent leaking what it can read (the workspace, its Claude token) through an allowed destination such as GitHub.

## Decision

- **Zone.** A dedicated VLAN in the 6XX range (VMID 601 gives VLAN 60, `192.168.60.0/24`), default-deny in both directions at OPNsense.
- **Inbound.** SSH only, from two sources: the maintainer client ([ADR 0055](../0055-maintainer-client-access-to-the-coding-agent-host/revision-000.md)) and the CD agent for provisioning ([ADR 0054](../0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md)). Each is source-restricted, with sshd enforcing the pairing per account.
- **Outbound.** Only through a domain-filtering forward proxy whose allowlist is derived from what Claude Code and the repo's tooling actually fetch. Direct egress is denied.
- **DNS.** The host resolves through a resolver that serves no internal zones.
- **Tailnet.** The host does not join Tailscale, and the subnet router's advertised routes never include its VLAN.
- **Rules.** Hand-built and documented in a topic doc first; moved into Tofu when the OPNsense day-2 project lands.

## Alternatives considered

- **Per-host firewall only.** Root on the host can rewrite it. Rejected as the authoritative layer.
- **Domain-named firewall aliases instead of a proxy.** Registries and GitHub sit behind shared CDN addresses, so IP-resolved aliases are broad and drift. Kept as a fallback if a proxy is not viable.
- **A shared services VLAN.** Puts the untrusted host on a subnet that AppRole CIDRs and other hosts already trust.

## Assumptions

- **Claim:** a domain-filtering forward proxy can run on OPNsense or a small dedicated VM at acceptable cost against the node's headroom.
  **Breaks if wrong:** egress falls back to domain-named aliases, with the drift described above.
  **Checked by:** a spike on a scratch VLAN, measuring resources and filtering by host name.
- **Claim:** a guest on the shared VLAN-aware bridge cannot send tagged frames into another VLAN and cannot reach the Proxmox management address.
  **Breaks if wrong:** the VLAN is not a boundary and a per-VM Proxmox firewall becomes mandatory.
  **Checked by:** probes from a scratch VM in the new VLAN.
- **Claim:** VLAN 60 clients can use a resolver that serves no internal zones while the maintainer and CD agent still reach the host by address.
  **Breaks if wrong:** the resolver design interacts with [ADR 0040](../0040-dns-for-tofu-provisioned-vms/revision-000.md) and needs its own decision.
  **Checked by:** reading how 0040's second BIND9 is planned, then a scratch-VLAN test.

## Consequences

- Allowed destinations remain an exfiltration channel for anything the agent can read. This is accepted.
- The allowlist needs upkeep as the repo's tooling changes.
- The first rules are hand-maintained, which is drift-prone until they move into Tofu.

## Invariants

- No flow from the VLAN to any other internal VLAN, OpenBao, the CD agent, the workstation, or the Proxmox management address.
- Inbound sessions are stateful and source-restricted; nothing is initiated from the VLAN into another zone.
- The VLAN's subnet is inside no AppRole CIDR binding.

## Non-goals

- Preventing exfiltration through allowed destinations.
- TLS inspection ([ADR 0039](../0039-intrusion-detection-scope/revision-000.md) keeps the lab's TLS uninspected). The proxy filters on the requested host name only.

## Validation

Probes run from a canary VM in the same VLAN under the same rules, outside the coding-agent host, since a compromised host cannot be trusted to report on itself. The exported rule set is compared against the topic doc.
