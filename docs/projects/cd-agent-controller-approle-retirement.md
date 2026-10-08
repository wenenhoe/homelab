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

Implements [ADR 0047 (First-credential bootstrap)](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md), `approved`: how `controller` authenticates to mint on-demand tokens once its standing AppRole is gone.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Retire `controller`'s standing AppRole | Not started | `controller` holds no AppRole `secret_id`; admin and debug access logs in with a CIDR-bound step-ca client certificate for a short-lived token, per ADR 0047 |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — Retire `controller`'s AppRole

Once the agent host and its AppRoles are live and proven, in this order:

1. Remove the weekly `check-freshness` user timer from `controller`
   (`tools/cloud_credentials/systemd/`). The same check now runs from
   `cd-agent-freshness`, and the timer logs in with the AppRole being
   deleted.
2. Run the snapshot push from `cd-agent-snapshot` instead of
   `snapshot-push.sh` on `controller`. `controller`'s policy grants the
   `sys/storage/raft/snapshot` read it uses, and deleting the AppRole
   removes it.
3. Add the second step-ca provisioner by hand, with its template checked
   in and its password held offline and never stored in OpenBao. Issue
   `controller`'s client certificate once with it, renew it over mTLS, and
   create a `cert` role bound to its common name, the organizational unit
   the template stamps, and its fixed address
   ([ADR 0047 (First-credential bootstrap)](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md)).
4. Delete `controller`'s Era A AppRole and its policy.

## Acceptance criteria

- [ ] `controller`'s AppRole, its `secret_id`, and its policy are deleted.
- [ ] Admin and debug access logs in with a step-ca client certificate from the second provisioner, bound to `controller`'s common name, organizational unit and fixed address, and receives a short-lived token, per ADR 0047.
- [ ] The `cert` role refuses the same common name when the original provisioner signs it, verified.
- [ ] The `check-freshness` user timer is gone from `controller`, and the snapshot push runs from `cd-agent-snapshot`.

## Open items

- The `cert` role's policy. The human-attended workflows that still need OpenBao from `controller` (generating and rotating secrets by hand, creating cloud leaf credentials the first time) decide it. It should be no wider than `controller.hcl` is today, minus what moved to `cd_agent`.
- A client certificate and key on `controller` is itself a standing credential, renewable for as long as the renewal runs. ADR 0047 treats it as narrower than a `secret_id`, since it is bound to a name, a unit and an address and expires unless renewed. If renewal lapses, re-issuing it needs the offline provisioner password. If the goal is no standing credential at all, this design does not meet it.

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
