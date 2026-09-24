---
id: PROJ-coding-agent-management
title: Coding-Agent Host Lifecycle
type: project
status: not-started
blocked: false
summary: Rebuild-first management of the coding-agent host from the Tofu definition, with a dedicated key and a CD-agent job that holds nothing else.
decision: ADR-0054/0
super_project: coding-agent-host
track: lifecycle
depends_on:
  - project: PROJ-tofu-vm-provisioning
    reason: Rebuild-first needs the Tofu Ubuntu module to recreate the VM from its definition
  - project: PROJ-cd-agent
    reason: The management job and its separate execution identity run on the CD agent, which does not exist yet
  - project: PROJ-coding-agent-host
    reason: A rebuild reproduces the host that project builds
---

# Coding-Agent Host Lifecycle

Turns the hand-built host into one that is replaced from its Tofu definition on a schedule. Staged because the definition, the inventory and key separation, the CD-agent job, and the end-to-end rebuild are independent changes with different prerequisites.

## Scope

The host's Tofu definition, its dedicated SSH key and inventory resolution, the CD-agent job under a separate identity, the rebuild cadence, and a rebuild drill. Not in scope: splitting the shared key for other hosts ([`cd-agent.md`](cd-agent.md)) and the host's build ([`coding-agent-host.md`](coding-agent-host.md)).

## Decision

Implements [ADR 0054](../decisions/0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md), `working`. Its one assumption depends on the outcome of [ADR 0044](../decisions/0044-prod-automation-trigger-and-execution/revision-000-a.md).

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Tofu definition of the host from the Ubuntu module | Not started | `tofu plan` reproduces the hand-built VM's shape |
| 2 | Group-level key override and a CI check on it | Not started | The inventory resolves the host's own key, and CI fails if it resolves the shared one |
| 3 | CD-agent job under an identity holding only the host's key | Not started | The job runs with no OpenBao token and no other host key, and plays use no `fetch` or `synchronize` |
| 4 | Rebuild drill and cadence | Not started | A full rebuild from the definition passes the host's acceptance criteria, and a cadence is set |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] The host is rebuilt end to end from its Tofu definition.
- [ ] The CD agent's job for the host holds no credential other than the host's key.
- [ ] CI fails if the host resolves the shared key.
- [ ] The management account accepts connections only from the CD agent.

## Risks

- Until the CD agent exists, rebuilds are run from the operator host, which holds the host's key ([ADR 0058](../decisions/0058-where-operator-work-runs/revision-000.md)).
- Each rebuild needs an interactive Claude login and loses unfetched work.

## Open items

- Rebuild cadence.

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
