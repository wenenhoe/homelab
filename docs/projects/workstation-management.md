---
id: PROJ-workstation-management
title: Maintainer Workstation
type: project
status: not-started
blocked: false
summary: Set up the maintainer's laptop as the workstation with WSL2 under a memory cap, a credential audit, and no desktop assistant with local tool access.
decision: ADR-0056/0
super_project: controller-separation
---

# Maintainer Workstation

Makes the maintainer's laptop work as the workstation under [ADR 0056 (Workstation credentials)](../decisions/0056-credentials-held-by-the-maintainer-workstation/revision-000.md). The laptop is not provisioned or converged from the repo, so this project records what it must hold and how that is checked. Staged because the repo's checks must run on the laptop, and the audit and the assistant rule are separate changes. Retiring VM 401 once the laptop and the operator host can do its work is [`vm-401-retirement.md`](vm-401-retirement.md).

## Scope

The laptop's WSL2 instance under a memory cap running the repo's checks, the push credential, the credential audit as a repeatable script, and keeping desktop assistants with local tool access off the laptop. Not in scope: the hardware-backed key registered on the operator host ([`operator-host.md`](operator-host.md)), the controller's move ([`operator-host-takeover.md`](operator-host-takeover.md)), retiring VM 401 ([`vm-401-retirement.md`](vm-401-retirement.md)), the laptop's client entry for the coding-agent host ([`coding-agent-access-path.md`](coding-agent-access-path.md)), deleting the AppRole ([`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)), and Tofu credential custody ([ADR 0048 (Tofu credentials)](../decisions/0048-where-tofu-credentials-live/revision-000.md)).

## Decision

Implements [ADR 0056 (Workstation credentials)](../decisions/0056-credentials-held-by-the-maintainer-workstation/revision-000.md), `approved`. [`vm-401-retirement.md`](vm-401-retirement.md) also names the revision and closes last, so it accepts it.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | WSL2 under a memory cap, and the push credential on the laptop | Not started | A change is checked with `pre-commit`, `pytest`, and a Molecule scenario in WSL2, reviewed, and pushed from the laptop |
| 2 | Audit as a repeatable script run on the laptop | Not started | A script over the Windows profile and the WSL2 home lists credential-shaped paths and fails on any beyond the push credential, the coding-agent host key, and the operator-host key's handle file |
| 3 | Keep desktop assistants with local tool access off the laptop | Not started | None is installed in Windows or in WSL2 |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] The repo's checks run in WSL2 under a memory cap, and a change can be reviewed and pushed from the laptop.
- [ ] No readable infrastructure credential exists on the laptop, and the audit passes.
- [ ] No desktop assistant with local tool access runs on the laptop, in Windows or in WSL2.
- [ ] The laptop's required setup and the audit are described in a topic doc.

## Risks

- The laptop is not converged from the repo, so the audit and the no-assistant rule hold only when they are run and kept; nothing enforces them between runs.
- A memory-capped WSL2 may not fit every Molecule scenario. The ones that do not run on the coding-agent host, and an open exploration of the coding-agent host's runtime and the sizing assumption in [ADR 0051 (Coding-agent isolation)](../decisions/0051-coding-agent-execution-isolation/revision-000.md) settle which.
- If routine work keeps needing the operator host, ADR 0056's reconsideration trigger applies and the reduction is revisited, not worked around.

## Open items

- The docs describe `controller` as a laptop ([`openbao-auth.md`](../topics/secrets/openbao-auth.md)), while VM 401 has run the tooling, so the laptop may already hold copies of these credentials. Inventory what it holds before Stage 1.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
