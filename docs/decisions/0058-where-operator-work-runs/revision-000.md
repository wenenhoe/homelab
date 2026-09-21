---
id: ADR-0058
revision: 0
type: adr
title: Where operator work runs
solution: A small headless VM in VLAN 30, reachable over SSH only from the maintainer's laptop, that becomes the controller
summary: Where Ansible, Tofu, the tools utilities, and break-glass access run, on a host that holds the infrastructure credentials and handles no untrusted content.
topic: deployment-platform
status: working
related: [ADR-0013, ADR-0020, ADR-0044, ADR-0047, ADR-0048, ADR-0053, ADR-0056]
---

# 0058. Where operator work runs

## Problem

Ansible, Tofu, the `tools/` utilities, and break-glass access to infrastructure run on a host that holds the infrastructure credentials and does not handle untrusted content or interactive desktop work.

## Context

The controller is VM 401 today, a desktop ([`tofu-vm-provisioning.md`](../../projects/tofu-vm-provisioning.md)). [ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md) moves every infrastructure credential off it.

The credentials to place: the file cache (`main-domain` and the AppRole pair), the shared SSH key, Tofu's Proxmox, OPNsense, and state credentials, on-demand OpenBao admin access through the native `bao` binary ([ADR 0034](../0034-operator-access-to-the-openbao-cli/revision-000.md)), and the backup GPG private key. That key is offline and is imported on the controller only for a restore ([`disaster-recovery.md`](../../disaster-recovery.md)).

The controller reaches managed hosts over SSH, OpenBao's API, Proxmox and OPNsense APIs, and the Tofu state bucket on `storage`. Its Internet destinations are package and release hosts, the cloud providers' APIs, and Telegram. Every one of these flows is outbound: Ansible pushes over SSH, and no host or service filters by the controller's address or calls back to it. The repo is public, so it pulls `main` without a credential. [`operator-host.md`](../../projects/operator-host.md) lists the flows.

The CD agent absorbs deploy, maintenance, rotation, and freshness ([`cd-agent.md`](../../projects/cd-agent.md)) but not Tofu or break-glass access, and it has zero inbound ports ([ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-a.md)).

The 3XX range, VLAN 30, is reserved and unused ([`vm-provisioning.md`](../../vm-provisioning.md)). The Tailscale subnet router advertises only VLAN 20 today, and the design already expects VLANs 30 and 40 routes to be added under Tailscale ACLs ([`tofu-vm-provisioning.md`](../../projects/tofu-vm-provisioning.md)). The tailnet's policy is the default allow-all grant, so every node reaches every advertised route. Tailscale denies by default once a policy lists specific grants, accepts a subnet CIDR as a destination, and rejects a policy save when a `tests` assertion fails. The controller AppRole is unbound by CIDR because the controller has had no fixed address ([`openbao-auth.md`](../../openbao-auth.md)).

**Threat model.** The adversary is a compromised workstation session or a compromised agent host. The asset is the infrastructure credentials. The attack path is any network path to this host, or content merged into `main` that it later runs. The second path is the review gate in [ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md). A third is a compromised dependency or tool on the host itself sending credentials out; the outbound allowlist below limits where, and cannot stop exfiltration through an allowed destination.

## Decision

A small dedicated headless VM in VLAN 30 (VMID 301, sized like the default Ubuntu VM in [`vm-provisioning.md`](../../vm-provisioning.md)) becomes the `controller`.

- **Access.** SSH only, from the maintainer's laptop with a dedicated key, over a Tailscale route to VLAN 30. The tailnet policy replaces its allow-all grant with explicit grants: the laptop reaches VLAN 30 on port 22, no other source has a grant for that route, existing access the maintainer needs is re-granted explicitly, and `tests` assert both. The workstation and the coding-agent host have no path to it.
- **Outbound.** Default-deny at OPNsense. Internal destinations are allowed by address and port; Internet destinations only through the domain-filtering proxy of [ADR 0053](../0053-network-reach-of-the-coding-agent-host/revision-000.md), under an allowlist for this VLAN that is separate from the coding-agent VLAN's.
- **Contents.** The toolchain (`uv`, Ansible, OpenTofu, `bao`, git) and the credentials above. No desktop, browser, editor beyond a terminal one, or software that handles untrusted content. It clones the public repo anonymously and holds no push credential.
- **Flow.** Changes reach it only as reviewed commits on `main`, pulled after the maintainer pushes them.
- **Own configuration.** Applied to itself over a local connection, like the `controller` group today. It patches itself with unattended security updates.
- **Shrinks over time.** Credentials leave it as the CD agent takes over their jobs; nothing new is added.

## Alternatives considered

- **Keep the controller on the workstation.** Leaves every infrastructure credential in the account that handles untrusted content. Rejected ([ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md)).
- **WSL2 on the laptop.** Puts the credentials on the maintainer's general-purpose machine. Rejected.
- **The CD agent.** Zero inbound ports and pollers only; interactive operator access does not fit. Rejected.
- **Wait for the CD agent.** Does not cover Tofu or break-glass, and is blocked on [ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-a.md). Rejected.

## Assumptions

- **Claim:** the proxy of [ADR 0053](../0053-network-reach-of-the-coding-agent-host/revision-000.md) can serve this VLAN's Internet destinations under its own allowlist, including the cloud providers' regional endpoints and GitHub release assets.
  **Breaks if wrong:** the allowlist falls back to domain-named aliases with the drift ADR 0053 describes, or the host is granted broader egress.
  **Checked by:** the same spike as ADR 0053's proxy assumption, run with this VLAN's destinations.

## Consequences

- One more VM on a node with limited headroom, and one more host to patch.
- The laptop holds a key to this host. A hardware-backed key for that path is a possible later hardening.
- The host has a fixed address, so the interim controller AppRole can be bound to its CIDR until the retirement project deletes it.
- Deploys, Tofu applies, and break-glass work become SSH sessions from the laptop.
- The tailnet policy becomes a maintained artifact. A wrong edit can lock out existing access, so it changes with tests and a preview, and a copy of the current policy is kept.
- The outbound allowlist needs upkeep as tooling changes.

## Invariants

- No network path from the workstation or the coding-agent host to this host.
- SSH is accepted only from the laptop's route, with one dedicated key.
- Outbound is default-deny.
- The host runs no software that handles untrusted content and holds no push credential.

## Non-goals

- Shrinking the credentials it holds, which the CD agent and retirement projects own.
- Hardware-backed keys.
- Preventing exfiltration through allowed destinations.

## Validation

Probes from the workstation, a scratch VM in the coding-agent VLAN, and a tailnet node other than the laptop confirm SSH to this host fails; a probe from the host to an unlisted destination fails. An audit of credential-shaped paths confirms it holds the controller credentials and the workstation holds none.

## Reconsideration triggers

- The CD agent takes on Tofu and break-glass, making a separate operator host unnecessary.
- A hardware-backed key path or a spare device changes where the credentials should sit.
