---
id: PROJ-cd-agent-controller-approle-retirement
title: Retire controller's Standing AppRole
type: project
status: not-started
blocked: false
summary: Delete controller's Era A AppRole; admin access mints short-lived tokens on demand.
decision: ADR-0047/0
super_project: pull-based-cd
track: credentials
depends_on:
  - project: PROJ-cd-agent
    reason: the AppRole is retired only once the agent host runs the jobs
  - project: PROJ-cd-agent-approles
    reason: the agent's own AppRoles must be live and proven first
---

# Retire controller's Standing AppRole

Last of three projects in the `pull-based-cd` initiative: once the [agent host](cd-agent.md) and [its AppRoles](cd-agent-approles.md) are live and proven, `controller`'s standing AppRole is deleted outright.

## Scope

Deleting `controller`'s Era A AppRole and its policy, and the on-demand token minting that replaces it. Not in scope: the agent host ([`cd-agent.md`](cd-agent.md)) and its AppRoles ([`cd-agent-approles.md`](cd-agent-approles.md)).

## Decision

Implements [ADR 0047](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md), still `working`: how `controller` authenticates to mint on-demand tokens once its standing AppRole is gone. Not started until that is settled.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Retire `controller`'s standing AppRole | Not started | `controller` holds no standing Vault credential; admin and debug access mints a short-lived token on demand per ADR 0047 |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — Retire `controller`'s AppRole

Once the agent host and its AppRoles are live and proven, delete `controller`'s Era A
AppRole outright, not narrow it. From that point `controller` holds no
standing Vault credential — any admin/debug access mints a fresh,
narrow, short-lived token on demand instead.

## Acceptance criteria

- [ ] `controller` holds no standing Vault credential.
- [ ] Admin and debug access mints a short-lived token on demand, per ADR 0047.
- [ ] The AppRole and its policy are deleted.

## Open items

- Stage 3's "mints a fresh, narrow, short-lived token on demand
  instead" doesn't specify how `controller` authenticates to do that
  minting once its standing AppRole is retired — see
  [`0047-first-credential-bootstrap-for-automated-processes/revision-000.md`](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md)'s
  leaning answer (mTLS via step-ca, same pattern `step_ca_cert` already
  proves) and its response-wrapping answer for handing Stage 2's
  `cd_agent` AppRole `secret_id` over at provisioning time.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
