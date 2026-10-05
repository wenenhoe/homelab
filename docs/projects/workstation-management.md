---
id: PROJ-workstation-management
title: Maintainer Laptop Setup
type: project
status: not-started
blocked: false
summary: Set up the maintainer's laptop as the workstation with WSL2 under a memory cap, a hardware-backed operator-host key, a credential audit, and no desktop assistant with local tool access.
decision: ADR-0056/0
super_project: controller-separation
track: workstation
phase: 1-management
---

# Maintainer Laptop Setup

Makes the maintainer's laptop work as the workstation under [ADR 0056](../decisions/0056-credentials-held-by-the-maintainer-workstation/revision-000.md). The laptop is not provisioned or converged from the repo, so this project records what it must hold and how that is checked. Staged because the repo's checks must run on it before VM 401 is retired, the operator-host key needs the operator host to exist, and the audit and the assistant rule are separate changes.

## Scope

The laptop's WSL2 instance under a memory cap running the repo's checks, the push credential, a hardware-backed key from each token registered on the operator host, the credential audit as a repeatable script, and keeping desktop assistants with local tool access off the laptop. Not in scope: the operator host ([`operator-host.md`](operator-host.md)), the laptop's client entry for the coding-agent host ([`coding-agent-access-path.md`](coding-agent-access-path.md)), and retiring VM 401 ([`workstation-capability-reduction.md`](workstation-capability-reduction.md)).

## Decision

Implements [ADR 0056](../decisions/0056-credentials-held-by-the-maintainer-workstation/revision-000.md), `approved`, which [`workstation-capability-reduction.md`](workstation-capability-reduction.md) also implements. The operator-host key in Stage 2 relies on [ADR 0058](../decisions/0058-where-operator-work-runs/revision-000.md), `working`: Stage 2 does not start before that revision's key assumption is resolved.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | WSL2 under a memory cap, and the push credential on the laptop | Not started | A change is checked with `pre-commit`, `pytest`, and a Molecule scenario in WSL2, reviewed, and pushed from the laptop |
| 2 | A hardware-backed key from each token registered on the operator host. Starts once [`operator-host.md`](operator-host.md) has built VM 302 | Not started | Both tokens log in to the operator host, and a login with no token present fails |
| 3 | Audit as a repeatable script run on the laptop | Not started | A script over the Windows profile and the WSL2 home lists credential-shaped paths and fails on any beyond the push credential, the coding-agent host key, and the operator-host key's handle file |
| 4 | Keep desktop assistants with local tool access off the laptop | Not started | None is installed in Windows or in WSL2 |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] The repo's checks run in WSL2 under a memory cap, and a change can be reviewed and pushed from the laptop.
- [ ] SSH to the operator host needs a token, and both tokens work.
- [ ] No readable infrastructure credential exists on the laptop, and the audit passes.
- [ ] No desktop assistant with local tool access runs on the laptop, in Windows or in WSL2.
- [ ] The laptop's required setup and the audit are described in a topic doc.

## Risks

- The laptop is not converged from the repo, so the audit and the no-assistant rule hold only when they are run and kept; nothing enforces them between runs.
- A memory-capped WSL2 may not fit every Molecule scenario. The ones that do not run on the coding-agent host, and [`coding-agent-molecule-runtime.md`](coding-agent-molecule-runtime.md) and the sizing assumption in [ADR 0051](../decisions/0051-coding-agent-execution-isolation/revision-000.md) settle which.

## Open items

- The docs describe `controller` as a laptop ([`openbao-auth.md`](../topics/secrets/openbao-auth.md)), while VM 401 has run the tooling, so the laptop may already hold copies of these credentials. Inventory what it holds before Stage 1.

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
