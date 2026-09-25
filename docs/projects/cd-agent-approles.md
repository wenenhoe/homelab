---
id: PROJ-cd-agent-approles
title: CD Agent AppRoles
type: project
status: de-risking
blocked: false
summary: Two CIDR-bound AppRoles for the CD agent (deploy and rotation).
decision: ADR-0020/1
super_project: pull-based-cd
track: credentials
---

# CD Agent AppRoles

Second of three projects in the `pull-based-cd` initiative, after [`cd-agent.md`](cd-agent.md). The CD agent's own AppRoles
([0020](../decisions/0020-automation-identity-and-access-scope/revision-000.md))
couldn't be scoped until OpenBao holds real credentials to build policies
against — which it now does.

## Scope

The two AppRoles `cd-agent-deploy` and `cd-agent-rotation`, their policies, and their CIDR binding. Not in scope: the host itself ([`cd-agent.md`](cd-agent.md)) and retiring `controller`'s AppRole ([`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)).

## Decision

Implements [ADR 0020, revision 001](../decisions/0020-automation-identity-and-access-scope/revision-001.md), still `working`, so this project is `de-risking` until that revision's open assumptions are resolved.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | `cd-agent-deploy` / `cd-agent-rotation` AppRoles, CIDR-bound | Not started | both roles exist with the policies in ADR 0020 revision 001, each bound to `cd_agent`'s fixed IP |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — AppRoles

Two CIDR-bound AppRoles, per the
[working decision](../decisions/0020-automation-identity-and-access-scope/revision-001.md):
`cd-agent-deploy` (read-only on `hosts/*` and
`cloud_credentials/leaf/*`) and `cd-agent-rotation` (create/update on
both `cloud_credentials/leaf/*` and `cloud_credentials/rotation/*`) —
no shared access between the two jobs, since a compromised deploy run
shouldn't be able to reach rotation-tier credentials or vice versa.

## Acceptance criteria

- [ ] Both AppRoles exist with the policies in ADR 0020 revision 001.
- [ ] Each is bound to `cd_agent`'s fixed IP (`secret_id_bound_cidrs` and `token_bound_cidrs`).
- [ ] Neither can read the other's paths, verified.

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
