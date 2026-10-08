---
id: ADR-0056
revision: 0
type: adr
title: Credentials held by the maintainer workstation
short: Workstation credentials
solution: The workstation, the maintainer's laptop, holds the push credential, the coding-agent host key and a hardware-backed key to the operator host, and no other readable infrastructure credential; the rest move to the operator host
summary: Which credentials the maintainer workstation holds, so a compromised routine session finds no infrastructure credential to read.
topic: security-hardening
status: approved
related: [ADR-0013, ADR-0020, ADR-0044, ADR-0047, ADR-0048, ADR-0050, ADR-0055, ADR-0058]
---

# 0056. Credentials held by the maintainer workstation

## Problem

The maintainer workstation handles content from an untrusted host and from the web. It holds no readable infrastructure credential; its routine work is reviewing and pushing changes, which needs only the credential to push them.

## Context

The workstation is the maintainer's Windows 11 laptop, a general-purpose machine that the repo does not provision or configure. The `controller` is VM 401 today, per [`tofu-vm-provisioning.md`](../../projects/tofu-vm-provisioning.md): a desktop that runs Ansible, Tofu, and the `tools/` utilities and holds the push credential. [ADR 0058 (Operator work host)](../0058-where-operator-work-runs/revision-000.md) moves the controller off it, and VM 401 is decommissioned once the operator host runs the controller. Per [`secrets.md`](../../topics/secrets/secrets.md) the controller holds a file cache with three permanent exceptions: `main-domain` and the `openbao-controller-role-id` and `-secret-id` AppRole pair.

`main-domain` is not sensitive. It is cached rather than stored in Vault because host names, including OpenBao's own, must resolve before Vault is reachable, and `tools/openbao_utils/client.py` builds OpenBao's URL from it.

The AppRole pair retires once the CD agent and its AppRoles run the jobs ([`cd-agent-controller-approle-retirement.md`](../../projects/cd-agent-controller-approle-retirement.md), [ADR 0047 (First-credential bootstrap)](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md)). One SSH key is shared across every managed host and possibly this machine ([`cd-agent.md`](../../projects/cd-agent.md)). Tofu's Proxmox, OPNsense, and state-backend credentials have no decided home ([ADR 0048 (Tofu credentials)](../0048-where-tofu-credentials-live/revision-000.md)), and the CD agent's job list does not include Tofu. Under [ADR 0050 (Agent changes to production)](../0050-agent-authored-changes-reaching-production/revision-000.md) the workstation also holds the only push credential.

CI runs `pre-commit` at both hook stages (which includes ansible-lint) and `pytest ansible/tests/ tools/tests/` on GitHub-hosted runners with no secrets and no file cache; the tests seed their own placeholder values. The checks for reviewing and pushing a change therefore need no credential. On the laptop they run in WSL2, which holds none and is no security boundary from Windows, so it follows the same rules as the laptop. Only the deploy-ordering check seeds placeholder secrets, and it runs in CI only.

The CD agent's own provisioning is deliberately outside its deploy loop ([ADR 0044 (CD agent trigger)](../0044-prod-automation-trigger-and-execution/revision-000-c.md)), so a human path to the infrastructure must persist. [ADR 0058 (Operator work host)](../0058-where-operator-work-runs/revision-000.md) gives it a home.

**Threat model.** The adversary is a compromised routine session: an editor or terminal handling content produced on the coding-agent host, or a desktop assistant or browser handling untrusted content, in Windows or in WSL2. The asset is every infrastructure credential the account can read, and the operator host the laptop can open. The attack paths are a same-account read and, for the operator host, use of the laptop's key by the compromised session.

## Decision

The workstation holds the GitHub push credential, the SSH key for the coding-agent host ([ADR 0055 (Coding-agent client access)](../0055-maintainer-client-access-to-the-coding-agent-host/revision-000.md)), and one hardware-backed SSH key for the operator host whose private half cannot be read from the laptop ([ADR 0058 (Operator work host)](../0058-where-operator-work-runs/revision-000.md)). It holds no other infrastructure credential: no shared SSH key, no OpenBao credential, no Tofu credential, no backup GPG key, no cached `main-domain`. Anything that needs one runs on the operator host.

This table shows which credentials the workstation holds and which it does not, as this revision decided it, not what it holds now.

| Credential | On the workstation |
| :--- | :--- |
| GitHub push credential | Held |
| SSH key for the coding-agent host | Held |
| Hardware-backed SSH key for the operator host | Held; its private half cannot be read from the laptop |
| Shared SSH key | Not held |
| OpenBao credential | Not held |
| Tofu credential | Not held |
| Backup GPG key | Not held |
| Cached `main-domain` | Not held |

Software that handles untrusted content with local tool access, such as a desktop assistant with file or tool access, does not run on the workstation, in Windows or in WSL2.

The credentials move to the operator host, not into thin air, and retire there as automation takes over: the AppRole pair through the retirement project, the shared key when it is split.

## Alternatives considered

- **Identity tiers on the workstation** (driving, maintainer, operator accounts). Two extra identities to maintain, and an account boundary on a shared kernel is weaker than a machine boundary. Rejected.
- **Wait for the CD agent to absorb the controller.** It absorbs deploys, maintenance, rotation, and freshness, not Tofu or break-glass access, and it is blocked on [ADR 0044 (CD agent trigger)](../0044-prod-automation-trigger-and-execution/revision-000-c.md). Rejected.
- **Move operator work onto the CD agent.** Its provisioning is deliberately decoupled from the deploy loop, and running Tofu there would give it authority over the VMs that include itself. Rejected.
- **A separate workstation machine or VM**, so the untrusted-content work is off the machine that holds the operator-host key. Costs a VM's memory on a node with limited headroom, or a second device, and needs its own remote access path. Rejected for the hardware-backed key and the residual risk accepted below.

## Consequences

- Deploys, Tofu applies, and break-glass work happen over SSH on the operator host, not on the workstation.
- A compromised workstation can still push a bad change. [ADR 0050 (Agent changes to production)](../0050-agent-authored-changes-reaching-production/revision-000.md)'s review step is the gate for that, not this decision.
- A compromised laptop session can still use the operator-host key when the maintainer authenticates with it: the hardware token stops the key being copied or used silently, but not what a compromised client sees or changes in a session the maintainer opens. This residual risk is accepted.
- The laptop is not converged from the repo, so the audit below is a script the maintainer runs, not a check that holds between runs.

## Invariants

- No infrastructure credential is readable on the workstation.
- The push credential exists only on the workstation.

## Non-goals

- The operator host's design ([ADR 0058 (Operator work host)](../0058-where-operator-work-runs/revision-000.md)).
- How the controller authenticates once its AppRole is retired ([ADR 0047 (First-credential bootstrap)](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md)).
- Where Tofu's credentials live ([ADR 0048 (Tofu credentials)](../0048-where-tofu-credentials-live/revision-000.md)).

## Validation

A scripted audit run on the laptop, over the Windows profile and the WSL2 home, lists credential-shaped paths (SSH keys, the file cache, Tofu and Proxmox tokens, OpenBao tokens, the backup GPG private key) and fails on any beyond the push credential, the coding-agent host key, and the operator-host key's handle file, which is useless without the token.

## Reconsideration triggers

- Routine work keeps needing an infrastructure credential the workstation no longer holds.
- The residual risk of a compromised laptop session is judged unacceptable, and a separate workstation machine is reconsidered.
