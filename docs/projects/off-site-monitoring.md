# Off-Site Monitoring Independence

**Status:** Not started

Three-stage plan to stop Beszel/Kuma monitoring from being a single
point of failure that lives entirely on the host (and site) it's
meant to be watching. Decision and full context are in
[`off-site-monitoring-independence-not-oci-tailscale-tunnel.md`](../decisions/drafts/off-site-monitoring-independence-not-oci-tailscale-tunnel.md);
this doc tracks build status only.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | Bring VM 202 (existing Tailscale subnet router) under repo management | Not started |
| 2 | New Proxmox VM for Beszel/Kuma, on-prem, separate from `security` | Not started |
| 3 | Relocate to OCI, reached over VM 202's existing subnet route | Not started |

## Stage detail

### Stage 1 — inventory VM 202

Starts with reading its actual current state (OS, Tailscale version,
ACL/tag configuration) — nothing about it is assumed correct or
known yet. Once inventoried, bring it under whatever configuration
management standard the rest of `managed_hosts` follows.

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

- Full-stack-vs-minimal-heartbeat choice for Stage 3 — deferred until
  Stage 1's inventory pass gives a clearer picture of what's actually
  worth duplicating remotely.
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
