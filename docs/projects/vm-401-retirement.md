---
id: PROJ-vm-401-retirement
title: VM 401 Retirement
type: project
status: not-started
blocked: false
summary: Remove every infrastructure credential from VM 401 and destroy it, once the operator host has taken the controller and the laptop is set up as the workstation.
decision: ADR-0056/0
super_project: controller-separation
depends_on:
  - project: PROJ-operator-host-takeover
    reason: VM 401's copies are removed only after the controller runs from the operator host
  - project: PROJ-workstation-management
    reason: the laptop has to be able to do VM 401's remaining work before the VM is retired
---

# VM 401 Retirement

Makes the clean cut that [ADR 0056 (Workstation credentials)](../decisions/0056-credentials-held-by-the-maintainer-workstation/revision-000.md) describes: after this, VM 401 no longer exists and holds nothing that authenticates to infrastructure. Staged because revoking the credentials and destroying the VM are separate changes, and the destruction follows proof that nothing still needs the VM.

## Scope

Retiring VM 401's copies of the controller credentials and its push credential, and decommissioning the VM. Not in scope: the operator host ([`operator-host.md`](operator-host.md), [`operator-host-takeover.md`](operator-host-takeover.md)), setting up the laptop ([`workstation-management.md`](workstation-management.md)), deleting the AppRole ([`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)), and Tofu credential custody ([ADR 0048 (Tofu credentials)](../decisions/0048-where-tofu-credentials-live/revision-000.md)).

## Decision

Implements [ADR 0056 (Workstation credentials)](../decisions/0056-credentials-held-by-the-maintainer-workstation/revision-000.md), `approved`. [`workstation-management.md`](workstation-management.md) names the same revision and closes first, so this project is the last to name it and accepts it when it closes.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Retire VM 401's copies: revoke its AppRole secret and its push credential, and delete the file cache, shared SSH key, Tofu and Proxmox credentials, and any OpenBao token | Not started | Each is revoked or deleted, and the PR lists what was checked |
| 2 | Decommission VM 401. Tofu's state is already held by a remote backend ([`state-and-credentials.md`](../topics/infra/tofu/state-and-credentials.md)), so destroying the VM loses none of it | Not started | The VM is destroyed and `vm-provisioning.md` no longer lists a workstation in the 4XX range |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] VM 401 is destroyed and every credential it held is revoked or deleted.
- [ ] The push credential exists only on the laptop.
- [ ] SSH to the operator host needs a token, and both tokens work.

## Risks

- VM 401 is the only place some tooling or state may still live; retire it only after the operator host and the laptop have done every operation it did.

## Open items

- Sizing reviewed against ADR 0037 revision 5: kept apart from `workstation-management.md`, which it depends on. The laptop setup is independent work, and the retirement follows `operator-host-takeover.md`.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
