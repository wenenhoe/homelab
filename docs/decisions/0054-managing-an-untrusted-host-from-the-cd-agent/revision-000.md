---
id: ADR-0054
revision: 0
type: adr
title: Managing an untrusted host from the CD agent
solution: Rebuild from the Tofu definition on a schedule, a dedicated key and inventory group, and a management job with its own identity
summary: How a host that runs untrusted code is built and kept patched by a controller holding production credentials, without either side inheriting the other's authority.
topic: security-hardening
status: working
related: [ADR-0020, ADR-0043, ADR-0044, ADR-0048]
---

# 0054. Managing an untrusted host from the CD agent

## Problem

A host that runs untrusted code is built and patched by automation that also holds production credentials. The host gains none of that authority, and the automation does not trust what the host reports back.

## Context

`inventory.yaml` sets one `ansible_ssh_private_key_file` under `all.vars`, so every host, including any added later, inherits the shared infrastructure key unless a narrower value overrides it. [`cd-agent.md`](../../projects/cd-agent.md) already records that this key is shared and unsplit.

`managed_hosts` receives Docker, Caddy, and compose apps from `deploy.yaml`; `patched_hosts` receives `maintenance.yaml`. The `network_infra` group shows the pattern for a host that should receive neither deploys nor the general key.

The CD agent ([ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-a.md)) does not exist yet. Until it does, provisioning is run from the workstation, as it is for every host today.

Converging in place does not remove an implant, and a controller running against a compromised host ingests its facts and task results. Provisioning a VM from the Tofu definition ([`vm-provisioning.md`](../../vm-provisioning.md)) is repeatable and starts from a known image.

**Threat model.** The adversary controls the target host. The asset is the controller's credentials and its other targets. The attack path is the management connection and the data returned over it.

## Decision

- **Rebuild first.** The host is replaced from the Tofu definition on a schedule and on suspicion of compromise. Between rebuilds it patches itself with unattended security updates, so Ansible reaches it only as part of a rebuild or a deliberate re-converge.
- **Own inventory group.** The host is in none of `managed_hosts`, `app_hosts`, or `patched_hosts`, so no existing play or job reaches it with a shared key.
- **Own key and account.** A dedicated SSH key for a management account named per the repo's `<x>admin` convention, overriding the `all.vars` key at group level. The account is root-equivalent on the host by design; the control is the direction of trust, not narrow sudo.
- **Own execution identity.** The CD agent's job for this host runs under an identity holding only that key: no OpenBao token and no other host's key. Plays against it use no `fetch` or `synchronize`, and treat facts and registered results as untrusted input.
- **Source-restricted.** The management account is accepted only from the CD agent's address ([ADR 0053](../0053-network-reach-of-the-coding-agent-host/revision-000.md)).

## Alternatives considered

- **Periodic in-place convergence.** Cannot evict a persistent implant, and keeps a live privileged session into an untrusted host. Kept only for deliberate re-converges.
- **`ansible-pull` on the host.** Runs repository content as root on the untrusted host itself. Rejected.
- **Manual maintenance.** Drifts and does not scale to rebuild-first.

## Assumptions

- **Claim:** whichever [ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-a.md) candidate is approved can run a job under an execution identity separate from the CD agent's general deploy and rotation identities.
  **Breaks if wrong:** the management key sits alongside the production credentials and the separation is lost.
  **Checked by:** reading the approved candidate's execution model, or a spike.

## Consequences

- Each rebuild ends with one interactive Claude `/login`, and unfetched work is gone ([ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md)).
- Rebuild-first depends on the Tofu Ubuntu module ([`tofu-vm-provisioning.md`](../../projects/tofu-vm-provisioning.md)); until it lands the VM is built by hand.
- The rebuild cadence is a project decision, not fixed here.

## Invariants

- The host holds no credential that authenticates it to the CD agent or to any host the CD agent manages.
- No job that holds production credentials also holds the host's management key.
- The SSH key the inventory resolves for the host is never the shared one.

## Non-goals

- Splitting the shared key for the other managed hosts (tracked in [`cd-agent.md`](../../projects/cd-agent.md)).
- The host's OS hardening baseline ([ADR 0043](../0043-host-os-hardening-baseline/revision-000.md)), which it inherits.

## Validation

A CI check that the host's group resolves to its own key and to no shared key. A rebuild exercised end to end from the Tofu definition.
