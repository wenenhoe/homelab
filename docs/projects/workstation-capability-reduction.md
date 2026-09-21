---
id: PROJ-workstation-capability-reduction
title: Strip the Workstation of Infrastructure Credentials
type: project
status: not-started
blocked: false
summary: Remove every infrastructure credential and the controller tooling from VM 401 once the operator host runs the controller.
decision: ADR-0056/0
super_project: controller-separation
track: workstation
phase: 2-reduction
depends_on:
  - project: PROJ-operator-host
    reason: The credentials and tooling are removed from VM 401 only after the operator host performs every controller operation
  - project: PROJ-workstation-management
    reason: The credential audit is part of the workstation role
---

# Strip the Workstation of Infrastructure Credentials

The clean cut: after this, VM 401 reviews agent work and pushes it, and holds nothing that authenticates to infrastructure. Staged because removal must follow proof that the operator host works, and the audit that keeps it true needs the workstation role.

## Scope

Retiring VM 401's copies of the controller credentials and tooling, the credential audit as a repeatable check, and moving desktop assistants with local tool access off the workstation. Not in scope: the operator host ([`operator-host.md`](operator-host.md)), deleting the AppRole ([`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)), and Tofu credential custody ([ADR 0048](../decisions/0048-where-tofu-credentials-live/revision-000.md)).

## Decision

Implements [ADR 0056](../decisions/0056-credentials-held-by-the-maintainer-workstation/revision-000.md), `working`, whose one assumption is checked before Stage 1 runs.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Check that review and push need no credential: `pre-commit`, the `tools/` tests, and ansible-lint on a clone with no secrets | Not started | The assumption in ADR 0056 is resolved and the revision can be `approved` |
| 2 | Retire VM 401's copies: revoke its AppRole secret, delete the file cache, shared SSH key, Tofu and Proxmox credentials, any OpenBao token, and the Ansible, Tofu, and `bao` tooling | Not started | The audit finds only the push credential and the coding-agent host key |
| 3 | Audit as a repeatable check in the workstation role | Not started | A script lists credential-shaped paths and fails on any beyond those two |
| 4 | Move desktop assistants with local tool access off the workstation | Not started | None is installed on it |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] No infrastructure credential is readable on the workstation.
- [ ] The push credential exists only on the workstation.
- [ ] The audit passes and is described in a topic doc.
- [ ] No desktop assistant with local tool access runs on the workstation.

## Risks

- If routine work keeps needing the operator host, the assumption in ADR 0056 was wrong and the reduction has to be revisited, not worked around.

## Open items

- The docs describe `controller` as a laptop ([`openbao-auth.md`](../openbao-auth.md)), while VM 401 has run the tooling. Any other machine that holds copies of these credentials must be stripped the same way, and is not yet inventoried.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
