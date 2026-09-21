---
id: PROJ-workstation-management
title: Maintainer Workstation Management
type: project
status: not-started
blocked: false
summary: Bring VM 401 under Ansible management from the operator host, with SSH client configuration and a TLS remote desktop.
decision: ADR-0057/0
super_project: controller-separation
track: workstation
phase: 1-management
depends_on:
  - project: PROJ-operator-host
    reason: The play is applied from the operator host over SSH, which must exist first
---

# Maintainer Workstation Management

Makes VM 401's configuration reproducible from the repo. Staged because the remote desktop assumption needs a spike, and the role, its tests, and the docs are separate reviewable changes.

## Scope

An inventory group and play for the workstation, a `workstation` role (management account, SSH client configuration for the coding-agent host, editor workspace-trust settings, git and pre-commit tooling, the remote desktop service), the role's Molecule scenario, and updating [`vm-provisioning.md`](../vm-provisioning.md)'s out-of-scope statement. Not in scope: the OS install, GPU passthrough, other desktops, and stripping credentials ([`workstation-capability-reduction.md`](workstation-capability-reduction.md)).

## Decision

Implements [ADR 0057](../decisions/0057-managing-the-maintainer-workstation-from-the-repo/revision-000.md), `working`. The project stays `not-started` while it waits on the operator host; the spike in Stage 1 can run on a scratch VM at any time.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike: the desktop's RDP service on Ubuntu 26.04 from a Windows client | Not started | The assumption in ADR 0057 is resolved and the revision can be `approved` |
| 2 | Inventory group and `workstation` role, applied from the operator host | Not started | The play converges idempotently against the workstation and the management account accepts only the operator host |
| 3 | Molecule scenario for what a container can cover | Not started | The scenario passes in CI and appears in the scenario matrix |
| 4 | Topic doc and the `vm-provisioning.md` scope update | Not started | `workstation.md` describes the behavior and `vm-provisioning.md` no longer calls VM 401 wholly out of scope |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] The play rebuilds the workstation's configuration from a fresh OS install without manual steps beyond the install and first login.
- [ ] The maintainer reaches a persistent desktop session from a Windows client over TLS.
- [ ] The workstation is in none of `managed_hosts`, `app_hosts`, or `patched_hosts`, and it has no network path to the operator host.
- [ ] The resulting behavior is described in `docs/workstation.md`.

## Agent handoff

- **Allowed to change:** not scoped yet; `allowed_paths` is added, in its own change, before an agent implements a stage.
- **Must not change:** other hosts' inventory entries and the `all.vars` SSH key.
- **Relevant files and interfaces:** `ansible/inventory/inventory.yaml` and `docs/network-infra.md` (the pattern for a host outside `managed_hosts`), [ADR 0054](../decisions/0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md) (management key handling).
- **Required checks:** `pre-commit run --all-files`; the role's Molecule scenario.

## Risks

- The desktop and remote-session settings cannot be tested in a container, so they rest on the spike and manual verification.

## Open items

- How Claude Desktop is packaged on Ubuntu 26.04 matters only if it stays on the workstation; [ADR 0056](../decisions/0056-credentials-held-by-the-maintainer-workstation/revision-000.md) moves it off.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
