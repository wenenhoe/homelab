---
id: PROJ-cd-agent
title: CD Agent Host
type: project
status: de-risking
blocked: false
summary: A dedicated, pull-based automation host that runs deploy, maintenance, rotation, and freshness jobs.
super_project: pull-based-cd
track: agent
---

# CD Agent Host

Replaces manual `ansible-playbook` deploys and rotation runs with a
dedicated, pull-based automation host. The second half of the
OpenBao+CD-agent migration this repo originally scoped together —
OpenBao itself is done; see ADRs
[0017](../decisions/0017-recovering-the-secrets-store-from-total-loss/revision-000.md) through
[0026](../decisions/0026-detecting-reads-of-high-value-secrets/revision-000.md)
and the `openbao-*.md` docs for that half.

This is the first of three projects in the `pull-based-cd` initiative; [`cd-agent-approles.md`](cd-agent-approles.md) and [`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md) cover its AppRoles and retiring `controller`'s standing AppRole.

## Scope

The `cd_agent` host: a dedicated LAN box with a fixed IP and zero inbound ports, running the jobs that replace manual `ansible-playbook` deploys and rotation runs. Not in scope: its AppRoles ([`cd-agent-approles.md`](cd-agent-approles.md)) and retiring `controller`'s standing AppRole ([`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)).

## Decision

No `decision:` is linked yet. This project implements [ADR 0044](../decisions/0044-prod-automation-trigger-and-execution/revision-000-a.md), which has two competing candidates: [000-a](../decisions/0044-prod-automation-trigger-and-execution/revision-000-a.md) (a pull-based agent) and [000-b](../decisions/0044-prod-automation-trigger-and-execution/revision-000-b.md) (a private Gitea or Forgejo). Neither is approved. Set `decision:` to the approved candidate before any production work; until then only throwaway spikes.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | `cd_agent` host — dedicated LAN box, fixed IP, pollers for deploy/maintenance/rotation/freshness/security-reporting (mechanism per ADR 0044) | Not started | ADR 0044 is settled (one candidate approved) and `decision:` is set; the host runs the deploy, maintenance, rotation, and freshness jobs with zero inbound ports |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — `cd_agent` host

A dedicated LAN host, fixed IP, zero inbound ports, running
systemd-timer pollers that invoke `preloop` against GitHub
Actions-format workflow files for deploy/maintenance/rotation/
freshness/security-reporting jobs. `preloop`'s CLI event-flag behavior beyond bare
`pull_request` is unverified — needs a spike before this stage's
deploy/rotation jobs are built on it. See the
[working decision](../decisions/0044-prod-automation-trigger-and-execution/revision-000-a.md)
this stage implements.

**Read before building this stage:**
[`0044-prod-automation-trigger-and-execution/revision-000-b.md`](../decisions/0044-prod-automation-trigger-and-execution/revision-000-b.md)
is a still-open, unresolved alternative that proposes replacing this
stage's mechanism entirely — a private, LAN-only Gitea *or Forgejo*
instance with an `act_runner`/`forgejo-runner`, dispatch-triggered on
push, instead of a `preloop` poller; which of Gitea or Forgejo is its
own open question inside that draft. It's a live draft, not a rejected
idea; the wording above shouldn't be read as having already decided
against it.

## Acceptance criteria

- [ ] ADR 0044 is settled and the host runs from the approved mechanism.
- [ ] The host exposes zero inbound ports.
- [ ] Deploy, maintenance, rotation, and freshness jobs run from it.

## Open items

- Whether Stage 1 stays a `preloop` poller or gets replaced by
  [`0044-prod-automation-trigger-and-execution/revision-000-b.md`](../decisions/0044-prod-automation-trigger-and-execution/revision-000-b.md)'s
  Gitea Actions approach — a live, unresolved fork. Resolve this
  before Stage 1 is actually built, not after.
- `preloop`'s CLI event-flag behavior (Stage 1) — spike needed before
  building on it.
- Which cloud credentials beyond B2/R2/OCI get rotation automation,
  and whether "rotation" means alert-only or full rotate-and-revoke,
  isn't scoped yet.
- A weekly security-reporting job: Trivy image scanning, redesigned as
  a PDF report sent to Telegram (trend visibility, not a CI gate) —
  needs `cd_agent` specifically for its Telegram secret access, which
  is why this wasn't feasible from `controller`. Previous CI-integrated
  image scanning was dropped for being mostly non-actionable noise
  (third-party images awaiting upstream rebuilds) — see
  [`security-scanning.md`](../security-scanning.md#why-no-image-cve-scanning).
  This reframes the same capability as informational rather than
  actionable, which may sidestep that problem. Not scoped beyond the
  idea yet.
- The shared SSH private key across every managed host (and possibly
  the maintainer's laptop) hasn't been split into a `cd_agent`-only
  key.

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
