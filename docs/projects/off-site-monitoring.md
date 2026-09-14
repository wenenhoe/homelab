---
id: PROJ-off-site-monitoring
title: "Off-Site Monitoring Independence"
type: project
status: in-progress
summary: "Stop Beszel/Kuma from being a monitoring single point of failure — bring the existing Tailscale subnet router under management, then a dedicated on-prem host, then OCI."
---

# Off-Site Monitoring Independence

**Status:** In progress

Three-stage plan to stop Beszel/Kuma monitoring from being a single
point of failure that lives entirely on the host (and site) it's
meant to be watching. Decision and full context are in
[`off-site-monitoring-independence-not-oci-tailscale-tunnel.md`](../decisions/drafts/off-site-monitoring-independence-not-oci-tailscale-tunnel.md);
this doc tracks build status only.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | Bring VM 202 (existing Tailscale subnet router) under repo management | Done |
| 2 | New Proxmox VM for Beszel/Kuma, on-prem, separate from `security` | Not started |
| 3 | Relocate to OCI, reached over VM 202's existing subnet route | Not started |

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

### Stage 3 — OCI relocation

The actual site-independence win. Reachable via VM 202's existing
subnet route — no new tunnel technology needed. Still open: whether
this relocates the full stack or a minimal heartbeat-only monitor (see
the decision draft's "Not yet done").

## Open items

- Full-stack-vs-minimal-heartbeat choice for Stage 3 — Stage 1's
  inventory pass (above) is done, but the choice itself is still open.
- OCI compute availability/budget for Stage 3 — not confirmed.

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
