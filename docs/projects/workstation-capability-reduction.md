---
id: PROJ-workstation-capability-reduction
title: Maintainer Workstation Capability Reduction
type: project
status: not-started
blocked: false
summary: Split the workstation into driving, maintainer, and operator tiers and retire each infrastructure credential from the tiers that no longer need it.
decision: ADR-0056/0
super_project: maintainer-workstation
track: capabilities
depends_on:
  - project: PROJ-workstation-management
    reason: The tiers, their accounts, and the credential audit are realized by the workstation role, which must exist first
---

# Maintainer Workstation Capability Reduction

Shrinks what a compromised routine session on the workstation can read. Staged because the tier split can happen now, while retiring individual credentials waits on the CD agent and the AppRole retirement.

## Scope

The three identity tiers and where each credential lives, the tier audit, and retiring the shared SSH key, cached `main-domain`, and remaining AppRole material from the tiers that no longer need them. Not in scope: deleting the AppRole and minting tokens on demand ([`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)), splitting the shared key for other hosts ([`cd-agent.md`](cd-agent.md)), and Tofu credential custody ([ADR 0048](../decisions/0048-where-tofu-credentials-live/revision-000.md)).

## Decision

Implements [ADR 0056](../decisions/0056-credentials-held-by-the-maintainer-workstation/revision-000.md), `working`. The project stays `not-started` while it waits on the workstation role, and becomes `de-risking` once its first assumption is being worked.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Tier split: three accounts and sessions, credentials moved to the tier that needs them | Not started | Each credential is readable only from its tier's account |
| 2 | Tier audit as a repeatable check | Not started | A script lists readable credential paths per account and fails on any outside its tier |
| 3 | Retire credentials as automation takes over: starts once [`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md) is done and the CD agent runs deploy and maintenance | Not started | The shared key leaves the maintainer tier, `main-domain` stays only in the operator tier, no AppRole material remains, and `secrets.md`'s list of permanent exceptions is updated |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] No infrastructure credential is readable from the driving or maintainer tier.
- [ ] The push credential is readable only from the maintainer tier.
- [ ] The operator tier runs no software that handles untrusted content.
- [ ] No AppRole material remains on the workstation once the retirement project is done.
- [ ] The tier audit passes and is described in a topic doc.

## Risks

- Friction between tiers may push routine work into the operator tier. The first assumption in ADR 0056 exists to catch this.
- Retirement cannot finish before the CD agent exists, which is itself waiting on ADR 0044.

## Open items

- Where each desktop assistant runs, under the rule in ADR 0056.
- The docs describe `controller` as a laptop ([`openbao-auth.md`](../openbao-auth.md)), while VM 401 runs the tooling today. Whether a laptop is also a controller, and so a second holder of these credentials, is unreconciled.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
