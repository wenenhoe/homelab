---
id: PROJ-workstation-management
title: Maintainer Workstation and VM 401 Retirement
type: project
status: not-started
blocked: false
summary: Set up the maintainer's laptop as the workstation with WSL2 under a memory cap, a hardware-backed operator-host key, a credential audit, and no desktop assistant with local tool access, then remove every infrastructure credential from VM 401 and retire it.
decision: ADR-0056/0
super_project: controller-separation
track: workstation
---

# Maintainer Workstation and VM 401 Retirement

Makes the maintainer's laptop work as the workstation under [ADR 0056 (Workstation credentials)](../decisions/0056-credentials-held-by-the-maintainer-workstation/revision-000.md), then makes the clean cut: after this, VM 401 no longer exists and holds nothing that authenticates to infrastructure. The laptop is not provisioned or converged from the repo, so this project records what it must hold and how that is checked. Staged because the repo's checks must run on the laptop before VM 401 is retired, the operator-host key needs the operator host to exist, the audit and the assistant rule are separate changes, and removal must follow proof that the operator host works and that the laptop can do VM 401's remaining work.

## Scope

The laptop's WSL2 instance under a memory cap running the repo's checks, the push credential, a hardware-backed key from each token registered on the operator host, the credential audit as a repeatable script, and keeping desktop assistants with local tool access off the laptop; then retiring VM 401's copies of the controller credentials and its push credential, and decommissioning the VM. Not in scope: the operator host ([`operator-host.md`](operator-host.md), [`operator-host-takeover.md`](operator-host-takeover.md)), the laptop's client entry for the coding-agent host ([`coding-agent-access-path.md`](coding-agent-access-path.md)), deleting the AppRole ([`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)), and Tofu credential custody ([ADR 0048 (Tofu credentials)](../decisions/0048-where-tofu-credentials-live/revision-000.md)).

## Decision

Implements [ADR 0056 (Workstation credentials)](../decisions/0056-credentials-held-by-the-maintainer-workstation/revision-000.md), `approved`. The operator-host key in Stage 2 relies on [ADR 0058 (Operator work host)](../decisions/0058-where-operator-work-runs/revision-000.md), `working`: Stage 2 does not start before that revision's key assumption is resolved.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | WSL2 under a memory cap, and the push credential on the laptop | Not started | A change is checked with `pre-commit`, `pytest`, and a Molecule scenario in WSL2, reviewed, and pushed from the laptop |
| 2 | A hardware-backed key from each token registered on the operator host. Starts once [`operator-host.md`](operator-host.md) has built VM 302 | Not started | Both tokens log in to the operator host, and a login with no token present fails |
| 3 | Audit as a repeatable script run on the laptop | Not started | A script over the Windows profile and the WSL2 home lists credential-shaped paths and fails on any beyond the push credential, the coding-agent host key, and the operator-host key's handle file |
| 4 | Keep desktop assistants with local tool access off the laptop | Not started | None is installed in Windows or in WSL2 |
| 5 | Retire VM 401's copies: revoke its AppRole secret and its push credential, and delete the file cache, shared SSH key, Tofu and Proxmox credentials, and any OpenBao token. Starts once [`operator-host-takeover.md`](operator-host-takeover.md) has moved the controller and Stages 1 to 4 are done | Not started | Each is revoked or deleted, and the PR lists what was checked |
| 6 | Decommission VM 401 | Not started | The VM is destroyed and `vm-provisioning.md` no longer lists a workstation in the 4XX range |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] The repo's checks run in WSL2 under a memory cap, and a change can be reviewed and pushed from the laptop.
- [ ] SSH to the operator host needs a token, and both tokens work.
- [ ] No readable infrastructure credential exists on the laptop, and the audit passes.
- [ ] No desktop assistant with local tool access runs on the laptop, in Windows or in WSL2.
- [ ] VM 401 is destroyed and every credential it held is revoked or deleted.
- [ ] The push credential exists only on the laptop.
- [ ] The laptop's required setup and the audit are described in a topic doc.

## Risks

- The laptop is not converged from the repo, so the audit and the no-assistant rule hold only when they are run and kept; nothing enforces them between runs.
- A memory-capped WSL2 may not fit every Molecule scenario. The ones that do not run on the coding-agent host, and [`coding-agent-molecule-runtime.md`](coding-agent-molecule-runtime.md) and the sizing assumption in [ADR 0051 (Coding-agent isolation)](../decisions/0051-coding-agent-execution-isolation/revision-000.md) settle which.
- If routine work keeps needing the operator host, ADR 0056's reconsideration trigger applies and the reduction is revisited, not worked around.
- VM 401 is the only place some tooling or state may still live; retire it only after the operator host and the laptop have done every operation it did.

## Open items

- The docs describe `controller` as a laptop ([`openbao-auth.md`](../topics/secrets/openbao-auth.md)), while VM 401 has run the tooling, so the laptop may already hold copies of these credentials. Inventory what it holds before Stage 1.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
