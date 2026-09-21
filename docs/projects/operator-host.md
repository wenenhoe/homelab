---
id: PROJ-operator-host
title: Operator Host
type: project
status: de-risking
blocked: false
summary: A headless VM in VLAN 30, reachable only from the maintainer's laptop, that takes over the controller's tooling and credentials.
decision: ADR-0058/0
super_project: controller-separation
track: operator
---

# Operator Host

Moves the controller off the workstation onto a small host that holds the infrastructure credentials and handles no untrusted content. Staged because an assumption needs checking first, the network zone and the host are separate changes, and moving each credential is a step to prove before the workstation is stripped ([`workstation-capability-reduction.md`](workstation-capability-reduction.md)).

## Scope

VLAN 30 and its rules, the Tailscale route and ACL for it, the VM, an `operator_host` role, and moving the toolchain and credentials onto it. Not in scope: stripping VM 401 ([`workstation-capability-reduction.md`](workstation-capability-reduction.md)), shrinking the credentials as the CD agent lands ([`cd-agent.md`](cd-agent.md), [`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)), and managing the workstation ([`workstation-management.md`](workstation-management.md)).

## Decision

Implements [ADR 0058](../decisions/0058-where-operator-work-runs/revision-000.md), `working`, so this project is `de-risking` until its assumption is resolved.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Review the tailnet ACL (the flow listing is done, below) | In progress | The assumption in ADR 0058 is resolved and the revision can be `approved` |
| 2 | VLAN 30 with default-deny rules built by hand, and the Tailscale route restricted to the laptop | Not started | The laptop reaches SSH on a scratch VM in the VLAN; the workstation and the coding-agent VLAN do not |
| 3 | VM 301 and the `operator_host` role, applied locally | Not started | The role converges idempotently and SSH accepts only the dedicated key |
| 4 | Move the controller: toolchain, `main-domain`, a freshly issued AppRole secret, Tofu credentials, the shared SSH key | Not started | A deploy in check mode, a `tofu plan`, and a `bao_session` login all succeed from the operator host |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 2 — required flows

Read from the playbooks, `tools/`, `restore_all.py`, and the docs. All are outbound from VLAN 30; the only inbound flow is SSH from the laptop's route.

| Destination | Port | Used for |
| :--- | :-: | :--- |
| Managed hosts, `tailscale` (VM 202), and later the coding-agent host and CD agent | 22 | Ansible, restore, provisioning; `sos-inventory.yaml` also reaches VLAN 20 hosts by static IP |
| `security` | 8200 | OpenBao API (Ansible, `hvac`, `bao`) |
| `security` | 22 | Reading step-ca's root cert; `init_unseal.py` over paramiko |
| `storage` | 443, 8333 | S3 through Caddy for `restore_all.py`'s rclone; Tofu state |
| Proxmox node | 8006 | Tofu |
| OPNsense | HTTPS | Tofu day-2, later |
| Internal DNS | 53 | The `internal.` and `lan.` zones |

Internet, over 443: GitHub (`git pull`, the `bao` binary, provider releases), PyPI, Ansible Galaxy, the OpenTofu registry, Ubuntu mirrors, Telegram, Cloudflare (API and R2), Backblaze B2, and Oracle Cloud (identity, object storage, and the Identity Domain URL).

## Acceptance criteria

- [ ] Every operation the controller performs today succeeds from the operator host.
- [ ] SSH to the operator host fails from the workstation and from a VM in the coding-agent VLAN.
- [ ] The operator host runs no desktop, browser, or software that handles untrusted content, and holds no push credential.
- [ ] The resulting behavior is described in `docs/operator-host.md`.

## Agent handoff

- **Allowed to change:** not scoped yet; `allowed_paths` is added, in its own change, before an agent implements a stage.
- **Must not change:** other hosts' inventory entries, the `all.vars` SSH key, existing OpenBao policies.
- **Relevant files and interfaces:** `ansible/inventory/inventory.yaml` (the `controller` group), `docs/openbao-auth.md` (issuing a new AppRole secret), `docs/network-infra.md`.
- **Required checks:** `pre-commit run --all-files`; the role's Molecule scenario.

## Risks

- OPNsense rules for VLAN 30 are hand-maintained until [`tofu-opnsense-day-2.md`](tofu-opnsense-day-2.md) lands.
- The laptop's key to this host is a single point of access; a hardware-backed key would harden it.
- The node has limited headroom for another VM.

## Open items

- Tofu's flows come from the docs, not code, since no Tofu exists yet. The Proxmox provider may need SSH to the node for some resources; check when the Tofu skeleton lands.
- The restore procedure on this host: import the backup GPG private key for the restore only, then remove it. It belongs in `docs/operator-host.md`.
- Binding the interim controller AppRole to this host's CIDR until the retirement project deletes it. Cheap, but only worth doing if the retirement is far off.
- Whether VM 301 is built by hand or waits for the Tofu Ubuntu module ([`tofu-vm-provisioning.md`](tofu-vm-provisioning.md)); the VM is small enough to build by hand.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
