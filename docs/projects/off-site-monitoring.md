---
id: PROJ-off-site-monitoring
title: "Off-Site Monitoring Independence"
type: project
status: in-progress
summary: "Stop Beszel/Kuma from being a monitoring single point of failure — bring the existing Tailscale subnet router under management, then a dedicated on-prem host, then GCP e2-micro."
---

# Off-Site Monitoring Independence

**Status:** In progress

Three-stage plan to stop Beszel/Kuma monitoring from being a single
point of failure that lives entirely on the host (and site) it's
meant to be watching. Stage 3's target changed from OCI to GCP's
e2-micro Always Free instance once OCI was earmarked for a dedicated
Wazuh instance instead — see
[`0045-security-event-collection-and-alerting/revision-000.md`](../decisions/0045-security-event-collection-and-alerting/revision-000.md). Decision and full context are in
[`0042-monitoring-that-survives-loss-of-the-homelab/revision-000.md`](../decisions/0042-monitoring-that-survives-loss-of-the-homelab/revision-000.md);
this doc tracks build status only.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | Bring VM 202 (existing Tailscale subnet router) under repo management | Done |
| 2 | New Proxmox VM for Beszel/Kuma, on-prem, separate from `security` | Not started |
| 3 | Relocate to GCP e2-micro, reached by extending VM 202's subnet route | Not started |

## Stage detail

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

### Stage 3 — GCP e2-micro relocation

The actual site-independence win. Reachable by extending VM 202's
existing subnet route to the new node — no new tunnel technology,
just a new route destination. OCI was the original target; it's now
reserved for a dedicated Wazuh instance instead (separate draft), so
this stage moved to GCP's Always Free e2-micro tier. Still open:
whether Beszel Hub + Uptime Kuma actually fit e2-micro's 1 GB RAM
together, and whether this relocates the full stack or a minimal
heartbeat-only monitor (see the decision draft's "Not yet done").

## Open items

- Full-stack-vs-minimal-heartbeat choice for Stage 3 — Stage 1's
  inventory pass (above) is done, but the choice itself is still open,
  and matters more now that the target is e2-micro's 1 GB RAM rather
  than OCI's 12 GB.
- Whether Beszel Hub + Uptime Kuma together actually fit e2-micro's
  1 GB RAM at this lab's scale — unverified, needs a time-boxed spike
  before any Ansible role targets it.
- Tailscale route extension from VM 202 to the GCP node — not yet
  built.
- Stage 3 is additionally gated on
  [`0047-first-credential-bootstrap-for-automated-processes/revision-000.md`](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md)
  reaching `decided` and on a not-yet-scoped hardening pass for the
  GCP host — both independent of the RAM spike above, and both block
  this stage moving to `Building` even if the RAM spike resolves
  favorably.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes) — run
before deleting this doc once every stage is Done.

- [ ] Every `Done` stage's rationale exists as a real ADR, or plainly
      didn't need one.
- [ ] Every `Done` stage's current behavior is in a topic doc.
- [ ] Every open item is resolved-and-promoted or moved to where it
      belongs next.
- [ ] Every cross-reference into this doc elsewhere in the repo is
      updated or removed.
