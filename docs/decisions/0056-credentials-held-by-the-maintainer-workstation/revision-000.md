---
id: ADR-0056
revision: 0
type: adr
title: Credentials held by the maintainer workstation
solution: Three identity tiers on the workstation, with each infrastructure credential held only by the tier that needs it and retired as automation takes over
summary: Which credentials and capabilities the maintainer workstation holds, and where, so a compromised routine session finds no infrastructure credential to read.
topic: security-hardening
status: working
related: [ADR-0013, ADR-0020, ADR-0044, ADR-0047, ADR-0048, ADR-0050, ADR-0055]
---

# 0056. Credentials held by the maintainer workstation

## Problem

The maintainer workstation holds only the credentials and capabilities its routine work needs. Each remaining high-value credential sits where a compromised routine session cannot read it.

## Context

The workstation (VM 401 today, per [`tofu-vm-provisioning.md`](../../projects/tofu-vm-provisioning.md)) is the `controller`: it runs Ansible, Tofu, and the `tools/` utilities, and it hosts the editor. Per [`secrets.md`](../../secrets.md) it holds a controller-side file cache with three permanent exceptions: `main-domain` and the `openbao-controller-role-id` and `-secret-id` AppRole pair.

`main-domain` is not sensitive. It is cached rather than stored in Vault because host names, including OpenBao's own, must resolve before Vault is reachable, and `tools/openbao_utils/client.py` builds OpenBao's URL from it.

The AppRole pair retires once the CD agent and its AppRoles run the jobs ([`cd-agent-controller-approle-retirement.md`](../../projects/cd-agent-controller-approle-retirement.md), [ADR 0047](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md)); admin access then mints short-lived tokens on demand.

One SSH key is shared across every managed host and possibly this machine ([`cd-agent.md`](../../projects/cd-agent.md)). Tofu's Proxmox, OPNsense, and state-backend credentials have no decided home ([ADR 0048](../0048-where-tofu-credentials-live/revision-000.md)), and the CD agent's job list does not include Tofu. Under [ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md) the workstation also holds the only push credential.

The CD agent's own provisioning is deliberately outside its deploy loop ([ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-a.md)), so a human path to the infrastructure must persist.

**Threat model.** The adversary is a compromised routine session: an editor opening content produced on the coding-agent host, or a desktop assistant or browser handling untrusted content. The asset is every infrastructure credential the account can read. The attack path is a same-account read.

## Decision

The workstation runs three identity tiers, each with its own account and desktop session.

- **Driving.** Reaches the coding-agent host ([ADR 0055](../0055-maintainer-client-access-to-the-coding-agent-host/revision-000.md)) and runs software that handles untrusted content with local tool access. Holds the host key and nothing else.
- **Maintainer.** Fetches, reviews, and pushes ([ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md)); edits local clones with workspace trust restricted. Holds the push credential and no infrastructure credential.
- **Operator.** Break-glass access and infrastructure changes: the shared SSH key until it is split, on-demand OpenBao admin access, Tofu credentials, and `main-domain`. Used deliberately, and runs no software that handles untrusted content.

Retirement follows the automation that replaces each credential:

- **AppRole pair:** removed from the workstation entirely by the retirement project.
- **Shared SSH key and `main-domain`:** leave the maintainer tier now and stay in the operator tier; the shared key leaves once the CD agent runs deploys and maintenance.
- **Tofu credentials:** stay in the operator tier unless [ADR 0048](../0048-where-tofu-credentials-live/revision-000.md) places them elsewhere.
- **Push credential:** maintainer tier only.

## Alternatives considered

- **One account.** Every credential is readable by a session that handles untrusted content. Rejected.
- **Move all operator work to the CD agent.** Its provisioning is deliberately decoupled from the deploy loop, and running Tofu there would give it authority over the VMs that include itself. Rejected.
- **A separate operator device.** Stronger than an account boundary on a shared kernel. The step up if an account boundary is judged insufficient.

## Assumptions

- **Claim:** once the CD agent runs deploy, maintenance, rotation, and freshness jobs, no routine maintainer workflow needs the shared key, `main-domain`, or a Vault credential.
  **Breaks if wrong:** the maintainer switches to the operator tier routinely and the split stops protecting anything.
  **Checked by:** reading which playbooks and `tools/` entry points a routine change needs against the approved [ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-a.md) job list, then working from the reduced account for a trial period.
- **Claim:** account separation with a desktop session per tier is an adequate boundary on this VM.
  **Breaks if wrong:** the operator tier moves to a separate VM or device.
  **Checked by:** the spike in [ADR 0057](../0057-managing-the-maintainer-workstation-from-the-repo/revision-000.md) and a review of what each account can reach.

## Consequences

- Moving content between tiers has friction: sessions do not share a clipboard, and that is the point.
- The operator tier is used rarely, so its procedures need to stay documented and exercised.
- Where a desktop assistant runs is a per-tool placement decision under the rule that software handling untrusted content with local tool access never runs in a tier that holds infrastructure credentials.

## Invariants

- No infrastructure credential is readable from the driving or maintainer tier.
- The push credential is readable only from the maintainer tier.
- The operator tier runs no software that handles untrusted content.

## Non-goals

- How `controller` authenticates once its AppRole is retired ([ADR 0047](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md)).
- Where Tofu's credentials live ([ADR 0048](../0048-where-tofu-credentials-live/revision-000.md)).
- Hardware-backed keys, a possible later revision.

## Validation

A scripted audit from each tier's account lists which credential paths it can read and fails on any outside its tier.

## Reconsideration triggers

- The account boundary proves insufficient, or a spare device makes a separate operator host practical.
- The CD agent takes on Tofu.
