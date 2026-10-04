---
id: PROJ-cd-agent-approles
title: CD Agent AppRoles
type: project
status: not-started
blocked: false
summary: Three CIDR-bound AppRoles for the CD agent (deploy, rotation and freshness).
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

The three AppRoles `cd-agent-deploy`, `cd-agent-rotation` and `cd-agent-freshness`, their policies, and their CIDR binding. Not in scope: the host itself ([`cd-agent.md`](cd-agent.md)) and retiring `controller`'s AppRole ([`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)).

## Decision

Implements [ADR 0020, revision 001](../decisions/0020-automation-identity-and-access-scope/revision-001.md), `approved`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | `cd-agent-deploy` / `cd-agent-rotation` / `cd-agent-freshness` AppRoles, CIDR-bound | Not started | both roles exist with the policies in ADR 0020 revision 001, each bound to `cd_agent`'s fixed IP |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — AppRoles

Three CIDR-bound AppRoles, per the
[decision](../decisions/0020-automation-identity-and-access-scope/revision-001.md):
`cd-agent-deploy` (read on `hosts/*` and `cloud_credentials/leaf/*`,
`create` but not `update` on `hosts/*`), `cd-agent-rotation`
(create/update on both `cloud_credentials/leaf/*` and
`cloud_credentials/rotation/*`, nothing under `hosts/*`) and
`cd-agent-freshness` (read-only on `cloud_credentials/leaf/*`,
`cloud_credentials/rotation/*` and `hosts/all/telegram/*`) — a
compromised deploy run shouldn't be able to reach rotation-tier
credentials, and the freshness check shouldn't be able to write any.

## Acceptance criteria

- [ ] All three AppRoles exist with the policies in ADR 0020 revision 001.
- [ ] Each is bound to `cd_agent`'s fixed IP (`secret_id_bound_cidrs` and `token_bound_cidrs`).
- [ ] `cd-agent-deploy` cannot read `cloud_credentials/rotation/*`, verified.
- [ ] `cd-agent-deploy` can create a missing `hosts/*` path and cannot update an existing one, verified.
- [ ] `cd-agent-rotation` can read no `hosts/*` path, verified.
- [ ] `cd-agent-freshness` can read the leaf, rotation and Telegram paths and write none of them, verified.

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
