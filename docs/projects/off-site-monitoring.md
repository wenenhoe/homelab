---
id: PROJ-off-site-monitoring
title: Off-Site Monitoring Relocation
type: project
status: de-risking
blocked: true
blocked_reason: no production credential goes to the GCP host until its hardening pass is scoped and done
summary: Relocate monitoring to a GCP e2-micro so it survives loss of the whole site.
decision: ADR-0049/0
super_project: off-site-monitoring
track: monitoring
phase: 2-off-site
depends_on:
  - project: PROJ-gcp-e2-micro-provisioning
    reason: the e2-micro and its provisioning identity must exist before a role or route can target it
---

# Off-Site Monitoring Relocation

Third stage of the plan to stop Beszel/Kuma monitoring from being a single point of failure that lives entirely on the host (and site) it's meant to be watching; the first two are [`monitoring-host-isolation.md`](monitoring-host-isolation.md). The target changed from OCI to GCP's e2-micro Always Free instance once OCI was earmarked for a dedicated Wazuh instance instead — see [`0045-security-event-collection-and-alerting/revision-000.md`](../decisions/0045-security-event-collection-and-alerting/revision-000.md).

## Scope

Relocating monitoring to a GCP e2-micro, and extending VM 202's Tailscale subnet route to it. Not in scope: the on-prem host ([`monitoring-host-isolation.md`](monitoring-host-isolation.md)), and creating the GCP project, its provisioning identity, and the e2-micro itself ([`gcp-e2-micro-provisioning.md`](gcp-e2-micro-provisioning.md)).

## Decision

Implements [ADR 0049 (Site-loss monitoring)](../decisions/0049-monitoring-that-survives-loss-of-the-site/revision-000.md), still `working`, so this project is `de-risking` until its open assumptions are resolved. It is also `blocked`: it waits on a decision, the off-site host's hardening pass, which [ADR 0049 (Site-loss monitoring)](../decisions/0049-monitoring-that-survives-loss-of-the-site/revision-000.md) names as a gate, not on another project.

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
reserved for a dedicated Wazuh instance instead ([ADR 0045 (Security event pipeline)](../decisions/0045-security-event-collection-and-alerting/revision-000.md)), so
this stage moved to GCP's Always Free e2-micro tier. Still open:
whether Beszel Hub + Uptime Kuma actually fit e2-micro's 1 GB RAM
together, and whether this relocates the full stack or a minimal
heartbeat-only monitor (see [ADR 0049 (Site-loss monitoring)](../decisions/0049-monitoring-that-survives-loss-of-the-site/revision-000.md)'s alternatives and open assumptions).

## Acceptance criteria

- [ ] Monitoring runs on the e2-micro with the route from VM 202 in place.
- [ ] A heartbeat reaches Telegram when the homelab is unreachable.
- [ ] ADR 0049 is settled, including the credential and hardening gates.

## Open items

- The GCP project, provisioning identity, and Tofu definition of the e2-micro — [`gcp-e2-micro-provisioning.md`](gcp-e2-micro-provisioning.md).
- Tailscale route extension from VM 202 to the GCP node — not yet
  built.
- The RAM fit, the full-stack-vs-minimal-heartbeat choice, the egress cap, and the credential and hardening gates are recorded as open assumptions in [ADR 0049 (Site-loss monitoring)](../decisions/0049-monitoring-that-survives-loss-of-the-site/revision-000.md); building starts once they are resolved.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
