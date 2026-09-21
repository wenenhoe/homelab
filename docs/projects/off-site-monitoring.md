---
id: PROJ-off-site-monitoring
title: Off-Site Monitoring Relocation
type: project
status: de-risking
blocked: true
blocked_reason: no production credential goes to the GCP host until ADR 0047 is approved, and its hardening pass is unscoped
summary: Relocate monitoring to a GCP e2-micro so it survives loss of the whole site.
decision: ADR-0049/0
super_project: off-site-monitoring
track: monitoring
phase: 2-off-site
---

# Off-Site Monitoring Relocation

Third stage of the plan to stop Beszel/Kuma monitoring from being a single point of failure that lives entirely on the host (and site) it's meant to be watching; the first two are [`monitoring-host-isolation.md`](monitoring-host-isolation.md). The target changed from OCI to GCP's e2-micro Always Free instance once OCI was earmarked for a dedicated Wazuh instance instead — see [`0045-security-event-collection-and-alerting/revision-000.md`](../decisions/0045-security-event-collection-and-alerting/revision-000.md).

## Scope

Relocating monitoring to a GCP e2-micro, and extending VM 202's Tailscale subnet route to it. Not in scope: the on-prem host ([`monitoring-host-isolation.md`](monitoring-host-isolation.md)).

## Decision

Implements [ADR 0049](../decisions/0049-monitoring-that-survives-loss-of-the-site/revision-000.md), still `working`, so this project is `de-risking` until its open assumptions are resolved. It is also `blocked`: it waits on decisions ([ADR 0047](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md)), not on another project.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Relocate to GCP e2-micro, reached by extending VM 202's subnet route | Not started | monitoring runs on the e2-micro, and a heartbeat reaches Telegram when the homelab is unreachable |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — GCP e2-micro relocation

The actual site-independence win. Reachable by extending VM 202's
existing subnet route to the new node — no new tunnel technology,
just a new route destination. OCI was the original target; it's now
reserved for a dedicated Wazuh instance instead ([ADR 0045](../decisions/0045-security-event-collection-and-alerting/revision-000.md)), so
this stage moved to GCP's Always Free e2-micro tier. Still open:
whether Beszel Hub + Uptime Kuma actually fit e2-micro's 1 GB RAM
together, and whether this relocates the full stack or a minimal
heartbeat-only monitor (see [ADR 0049](../decisions/0049-monitoring-that-survives-loss-of-the-site/revision-000.md)'s alternatives and open assumptions).

## Acceptance criteria

- [ ] Monitoring runs on the e2-micro with the route from VM 202 in place.
- [ ] A heartbeat reaches Telegram when the homelab is unreachable.
- [ ] ADR 0049 is settled, including the credential and hardening gates.

## Open items

- Tailscale route extension from VM 202 to the GCP node — not yet
  built.
- The RAM fit, the full-stack-vs-minimal-heartbeat choice, the egress cap, and the credential and hardening gates are recorded as open assumptions in [ADR 0049](../decisions/0049-monitoring-that-survives-loss-of-the-site/revision-000.md); building starts once they are resolved.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
