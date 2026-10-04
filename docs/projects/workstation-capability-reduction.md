---
id: PROJ-workstation-capability-reduction
title: Retire VM 401 and Its Credentials
type: project
status: not-started
blocked: false
summary: Remove every infrastructure credential and the controller tooling from VM 401, then retire it, once the operator host runs the controller and the laptop works as the workstation.
decision: ADR-0056/0
super_project: controller-separation
track: workstation
phase: 2-reduction
depends_on:
  - project: PROJ-operator-host
    reason: The credentials and tooling are removed from VM 401 only after the operator host performs every controller operation
  - project: PROJ-workstation-management
    reason: VM 401 is retired only after the laptop works as the workstation and holds the push credential
---

# Retire VM 401 and Its Credentials

The clean cut: after this, VM 401 no longer exists and holds nothing that authenticates to infrastructure. Staged because removal must follow proof that the operator host works and that the laptop can do VM 401's remaining work.

## Scope

Retiring VM 401's copies of the controller credentials and its push credential, then decommissioning the VM. Not in scope: the operator host ([`operator-host.md`](operator-host.md)), setting up the laptop ([`workstation-management.md`](workstation-management.md)), deleting the AppRole ([`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)), and Tofu credential custody ([ADR 0048](../decisions/0048-where-tofu-credentials-live/revision-000.md)).

## Decision

Implements [ADR 0056](../decisions/0056-credentials-held-by-the-maintainer-workstation/revision-000.md), `approved`, which [`workstation-management.md`](workstation-management.md) also implements.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Retire VM 401's copies: revoke its AppRole secret and its push credential, and delete the file cache, shared SSH key, Tofu and Proxmox credentials, and any OpenBao token | Not started | Each is revoked or deleted, and the PR lists what was checked |
| 2 | Decommission VM 401 | Not started | The VM is destroyed and `vm-provisioning.md` no longer lists a workstation in the 4XX range |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] VM 401 is destroyed and every credential it held is revoked or deleted.
- [ ] The push credential exists only on the laptop.

## Risks

- If routine work keeps needing the operator host, ADR 0056's reconsideration trigger applies and the reduction is revisited, not worked around.
- VM 401 is the only place some tooling or state may still live; retire it only after the operator host and the laptop have done every operation it did.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or named by a successor project.
- [ ] The linked revision is `accepted`, another project still names it, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
