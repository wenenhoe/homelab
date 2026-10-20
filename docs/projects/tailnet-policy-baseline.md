---
id: PROJ-tailnet-policy-baseline
title: Tailnet Policy Baseline
type: project
status: not-started
blocked: false
summary: Replace the tailnet's allow-all policy with explicit grants and tests, once, so the projects that add a route only add a grant.
---

# Tailnet Policy Baseline

The tailnet's policy is the default allow-all grant. Two projects need to tighten it before they advertise a route ([`operator-host.md`](operator-host.md) for VLAN 30 and [`coding-agent-network.md`](coding-agent-network.md) for the coding-agent VLAN), and each used to say that whichever went first replaces it. This project makes that one change once, so each of them only adds a grant, and the policy has a single owner until it is coded.

## Scope

Taking stock of what the maintainer reaches over the tailnet today, and replacing the allow-all grant with explicit grants for exactly that, plus `tests` that assert them. Not in scope: any new route's grant ([`operator-host.md`](operator-host.md), [`coding-agent-network.md`](coding-agent-network.md)), and putting the policy under Tofu, which builds on Tofu's root module ([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#tofu-project), [ADR 0059 (Tailnet policy)](../decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md)).

## Decision

No decision of its own. [ADR 0059 (Tailnet policy)](../decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md) decides that the policy is hand-edited in the console now and coded later, and this project is the hand edit. It names no `decision:` because that revision is `working` on an assumption about the Tofu provider, which this work does not touch.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Take stock of what the maintainer and the nodes reach over the tailnet today | Not started | Every source, destination and port in use is listed in a topic doc, with how it was found |
| 2 | Replace allow-all with explicit grants and `tests` | Not started | The saved policy grants exactly what Stage 1 lists, its `tests` pass, and every flow in the list still works from the node that uses it |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 2 — the edit

Copy the current policy first, and use the admin console's preview before saving. The policy is tailnet-wide, so an edit that tightens access can lock out existing access; "Reset to default" restores the allow-all grant. Add `tests` for each grant and for what must stay refused. A route is advertised or approved only after the saved policy grants it to the intended source alone, since while allow-all is in force every tailnet node would reach it.

## Acceptance criteria

- [ ] The policy is no longer allow-all, and every flow Stage 1 lists still works.
- [ ] `tests` assert each grant, and a save with a failing assertion is refused by the console.
- [ ] The topic doc names who adds a grant for a new route and how.

## Risks

- An edit that tightens access can lock out the maintainer or a node; the previous policy is copied first and the console's reset restores allow-all.
- Stage 1 can miss a flow that is used rarely; the exit lists how each was found, and a missed one is re-granted from the copy.

## Open items

- Where the topic doc lives; probably with [`network-infra.md`](../topics/infra/network-infra.md).

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
