---
id: PROJ-host-hardening-remaining-hosts
title: "Host Hardening on the Remaining Hosts"
type: project
status: not-started
blocked: false
summary: "Confirm the operator host, the CD agent, and the coding-agent host include the hardening baseline from their own builds, then settle ADR 0043."
decision: ADR-0043/0
depends_on:
  - project: PROJ-operator-host
    reason: The host does not exist until its project builds it
  - project: PROJ-cd-agent
    reason: The host does not exist until its project builds it
  - project: PROJ-coding-agent-host
    reason: The host does not exist until its project builds it
---

# Host Hardening on the Remaining Hosts

The remainder of [ADR 0043](../decisions/0043-host-os-hardening-baseline/revision-000.md)'s Decision: its scope names three hosts that are in none of `patched_hosts`' groups and include the `host_hardening` role from their own builds. Each build adds the role to its own stage ([`operator-host.md`](operator-host.md), [`cd-agent.md`](cd-agent.md), [`coding-agent-host.md`](coding-agent-host.md)); this project confirms each host ends up with the baseline and then settles the revision.

## Scope

Confirming the three hosts' effective apt configuration, and setting the revision `accepted` when the last is confirmed. Not in scope: any later area, the off-site hosts, and the Proxmox node (all per the decision's non-goals).

## Decision

Implements [ADR 0043](../decisions/0043-host-os-hardening-baseline/revision-000.md), `approved`. The role, the first area, and its application to `patched_hosts` are built and described in [`host-hardening.md`](../topics/infra/host-hardening.md).

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Operator host | Not started | The host's effective apt configuration passes the checks in [`host-hardening.md`](../topics/infra/host-hardening.md#verifying-a-host) |
| 2 | CD agent | Not started | Same |
| 3 | Coding-agent host | Not started | Same |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] Each of the three hosts has security-only unattended updates with no automatic reboot.
- [ ] [ADR 0043](../decisions/0043-host-os-hardening-baseline/revision-000.md)'s revision 0 is `accepted`, set in the PR that deletes this doc.

## Agent handoff

- **Must not change:** the allow-list beyond `automatic_updates`.
- **Relevant files and interfaces:** `ansible/roles/host_hardening/`, and each host's own role or play.
- **Required checks:** `pre-commit run --all-files`, and the `host_hardening` Molecule scenario.

## Risks

- A host project can land without including the role; this project's stage for that host is where it is caught.

## Open items

- Which areas follow the first, and in what order, is for successor projects; the collisions listed in ADR 0043's Context set the order in which they can be added.

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
