---
id: PROJ-operator-host
title: Operator Host
type: project
status: de-risking
blocked: false
summary: A headless VM in VLAN 30, reachable only from the maintainer's laptop, with its network rules, tailnet route and hardened baseline, ready to take the controller.
decision: ADR-0058/0
super_project: controller-separation
track: operator
---

# Operator Host

Builds the small host that will run the controller away from the workstation: the VLAN and its rules, the tailnet route and policy, the hardware-backed key, and the VM with its role. Staged because an assumption needs checking first and the network zone and the host are separate changes. Moving the controller's tooling and credentials onto it is [`operator-host-takeover.md`](operator-host-takeover.md), which starts once this host exists.

## Scope

VLAN 30 and its rules, the Tailscale route and ACL for it, the VM, and an `operator_host` role. Not in scope: the egress allowlist and moving the toolchain and credentials onto the host ([`operator-host-takeover.md`](operator-host-takeover.md)), setting up the laptop as the workstation and stripping and retiring VM 401 ([`workstation-management.md`](workstation-management.md)), and shrinking the credentials as the CD agent lands ([`cd-agent.md`](cd-agent.md), [`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)).

## Decision

Implements [ADR 0058 (Operator work host)](../decisions/0058-where-operator-work-runs/revision-000.md), `working`, so this project is `de-risking` until its assumptions are resolved. [`operator-host-takeover.md`](operator-host-takeover.md) names the same revision and carries it to `approved` and, as the last project to close, `accepted`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Verify the controller's flows and the tailnet policy | Done | The findings are in ADR 0058; the proxy assumption remains open |
| 2 | VLAN 30 with default-deny rules built by hand, its tailnet grant, and the hardware-backed key | Not started | The laptop logs in to a scratch VM in the VLAN with a key on each token, which resolves the key assumption in ADR 0058; the coding-agent VLAN and every other tailnet node cannot reach it |
| 3 | VM 302 and the `operator_host` role, applied locally, including the hardening baseline's role | Not started | The role converges idempotently and SSH accepts only the dedicated hardware-backed keys |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 2 — tailnet policy

Starts once [`tailnet-policy-baseline.md`](tailnet-policy-baseline.md) has replaced the allow-all grant. Add one grant to that policy: the laptop reaches VLAN 30 on `tcp:22`, and no other source has a grant for that route. Add `tests` that assert the laptop can reach VLAN 30 on 22 and cannot reach other ports, and that another tailnet node cannot reach it at all. Copy the current policy first, and use the admin console's preview before saving. The policy is hand-edited in the console now and coded later — see
[ADR 0059 (Tailnet policy)](../decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md).

### Stage 2 — required flows

Read from the playbooks, `tools/`, `restore_all.py`, and the docs. All are outbound from VLAN 30; the only inbound flow is SSH from the laptop's route.

| Destination | Port | Used for |
| :--- | :-: | :--- |
| Managed hosts, `tailscale` (VM 202), and later the coding-agent host and CD agent | 22 | Ansible, restore, provisioning; `sos-inventory.yaml` also reaches VLAN 20 hosts by static IP |
| `security` | 8200 | OpenBao API (Ansible, `hvac`, `bao`) |
| `security` | 22 | Reading step-ca's root cert; `init.py` and `unseal.py` over paramiko |
| `storage` | 443, 8333 | S3 through Caddy for `restore_all.py`'s rclone |
| Proxmox node | 8006 | Tofu |
| OPNsense | HTTPS | Tofu day-2, later |
| Internal DNS | 53 | The `internal.` and `lan.` zones |

Internet, over 443: GitHub (`git pull`, the `bao` binary, provider releases), PyPI, Ansible Galaxy, the OpenTofu registry, Ubuntu mirrors, Telegram, Cloudflare (API and R2), Backblaze B2, and Oracle Cloud (identity, object storage, and the Identity Domain URL).

## Acceptance criteria

- [ ] SSH to the operator host fails from a VM in the coding-agent VLAN, from any tailnet node other than the laptop, and from the laptop with no token present.
- [ ] The operator host runs no desktop, browser, or software that handles untrusted content, and holds no push credential.
- [ ] The host's network rules, route and role are described in `docs/topics/infra/operator-host.md`.

## Agent handoff

- **Allowed to change:** not scoped yet; `allowed_paths` is added, in its own change, before an agent implements a stage.
- **Must not change:** other hosts' inventory entries, the `all.vars` SSH key, existing OpenBao policies.
- **Relevant files and interfaces:** `ansible/inventory/inventory.yaml`, `docs/topics/infra/network-infra.md`.
- **Required checks:** `pre-commit run --all-files`; the role's Molecule scenario.

## Risks

- OPNsense rules for VLAN 30 are hand-maintained until [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md) lands.
- The laptop is the workstation and holds the only key to this host. The key is hardware-backed, and losing both tokens means recovery through the Proxmox node.
- The node has limited headroom for another VM.
- A tailnet policy edit is tailnet-wide and can lock out access.

## Open items

- Tofu's flows come from the docs, not code, since no Tofu exists yet. The Proxmox provider may need SSH to the node for some resources; check when the Tofu skeleton lands.
- Whether VM 302 is built by hand or waits for the Tofu Ubuntu module ([`tofu-vm-provisioning.md`](tofu-vm-provisioning.md)); the VM is small enough to build by hand.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
