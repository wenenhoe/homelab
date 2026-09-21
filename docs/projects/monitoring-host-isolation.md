---
id: PROJ-monitoring-host-isolation
title: Monitoring Host Isolation
type: project
status: building
blocked: false
summary: Bring VM 202 under management and move Beszel/Kuma onto a dedicated on-prem host.
decision: ADR-0042/0
super_project: off-site-monitoring
track: monitoring
phase: 1-on-prem
---

# Monitoring Host Isolation

First two stages of the plan to stop Beszel/Kuma monitoring from being a single point of failure that lives entirely on the host it's meant to be watching. Surviving the whole site going dark is [`off-site-monitoring.md`](off-site-monitoring.md).

## Scope

Bringing VM 202 under management, and a dedicated on-prem host for Beszel and Kuma. Not in scope: relocating monitoring off-site ([`off-site-monitoring.md`](off-site-monitoring.md)).

## Decision

Implements [ADR 0042](../decisions/0042-monitoring-that-survives-loss-of-the-homelab/revision-000.md), `approved`; this doc tracks build status only.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Bring VM 202 (existing Tailscale subnet router) under repo management | Done | VM 202 is in the `network_infra` inventory group, patched, and documented in `network-infra.md` |
| 2 | New Proxmox VM for Beszel/Kuma, on-prem, separate from `security` | Not started | Beszel and Kuma run on a dedicated on-prem VM, separate from `security` |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — inventory VM 202

Done. Current state read directly off the host and recorded in
[`network-infra.md`](../network-infra.md) — Ubuntu 26.04, Tailscale
1.102.3, no per-node ACL tags (tailnet-wide policy itself not yet
reviewed). Brought under management as its own `network_infra`
inventory group rather than `managed_hosts` (it runs no Docker/compose
apps); `maintenance.yaml` now patches it via the new `patched_hosts`
alias and installs `qemu_guest_agent` directly. See that doc for the
three manual prerequisites (SSH key, passwordless sudo, Python
interpreter) any new `network_infra` host needs first.

### Stage 2 — dedicated on-prem monitoring host

Partial win, stated honestly: isolates Beszel/Kuma from `security` as
a host/process, but doesn't address a whole-site outage. Worth doing
as its own step regardless, since it's lower-risk than jumping straight
to Stage 3 and validates the separation works before adding a WAN hop.

## Acceptance criteria

- [ ] VM 202 is under repo management and documented in `network-infra.md`.
- [ ] Beszel and Kuma run on a dedicated on-prem VM, separate from `security`.
- [ ] Monitoring keeps alerting when `security` itself is down.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
