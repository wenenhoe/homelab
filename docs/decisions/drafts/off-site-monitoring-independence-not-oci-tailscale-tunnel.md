---
id: DRAFT-off-site-monitoring-independence-not-oci-tailscale-tunnel
title: "Off-site monitoring independence — staged, reusing the existing Tailscale subnet router"
type: draft-adr
status: decided
---

# Off-site monitoring independence — staged, reusing the existing Tailscale subnet router

**Status:** Decided (staged) — see [`off-site-monitoring.md`](../../projects/off-site-monitoring.md) for build tracking

## Context

The idea: Beszel Hub and Uptime Kuma both already exist
(`docs/beszel.md`, `docs/uptime-kuma.md`), deployed on-prem on
`security`, with a connection model that already solves "no inbound
port needed" for the agent/push fleet. The real gap: both live
entirely on `security` — if `security`, or the whole homelab's
connectivity, goes down, nothing is left standing to notice or alert.
That's structurally the same threat model
[ADR 0010](../0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md) already solved for
backups, just never applied to monitoring.

Tailscale isn't absent from the
environment, only from the repo. **VM 202 already exists and already
runs as a subnet router**, routing Tailscale clients to the 4 managed
hosts — it's just not under Ansible/repo management yet. That's a
real gap in its own right, the same category as the scattered OpenBao
clients this repo has elsewhere: unmanaged-but-load-bearing
infrastructure that breaks silently because nothing tracks it. It also
means the actual mechanism needed for an eventual cloud-hosted monitor
to reach the 4 managed hosts already exists — no new tunnel technology,
just extending an existing Tailscale subnet route to a new node and
bringing the router itself under management.

## Decision

Staged, in this order:

1. **Bring VM 202 under repo management** — inventory it, document its
   role, apply whatever this repo's baseline-configuration standards
   are to it. Currently a blind spot; closing it is valuable
   independent of anything else here.
2. **New Proxmox VM for monitoring**, still on-prem — isolates
   Beszel/Kuma from `security` as a host/process, so an app crash or a
   `security`-specific problem doesn't take monitoring down with it.
   Honest limitation, stated plainly: this is still the same site,
   same power, same internet connection as everything else — it does
   **not** solve the "whole homelab goes dark" case. Partial win only.
3. **Relocate to GCP's e2-micro Always Free instance**, reached by
   extending the same Tailscale subnet route VM 202 already provides
   from Stage 1 to the new GCP node — this is the actual
   site-independence win, and it costs no new tunnel technology, only
   the actual work of adding GCP as a route destination (VM 202
   doesn't reach it for free just because the mechanism already
   exists elsewhere). OCI was the original target for this stage;
   it's now earmarked instead for a dedicated, on-prem-adjacent Wazuh
   instance — see
   [`r2-read-watcher-siem-replacement.md`](r2-read-watcher-siem-replacement.md)
   — which is why this stage moved to a different provider rather than
   sharing OCI with it.

## Not yet done

- Whether Stage 3 relocates the *entire* Beszel+Kuma stack, or only a
  minimal independent heartbeat (one Kuma monitor watching "is the
  homelab reachable from outside at all") — the fuller stack gives
  richer visibility but means bootstrapping Beszel's KEY/TOKEN and
  Kuma's admin account a second time, both documented as manual,
  DB-resident, and not template-able ahead of first boot. This
  question matters more now than it did against OCI: e2-micro's 1 GB
  RAM is the tighter of the two boxes this stage ever considered.
- VM 202's current configuration is now read and recorded in
  [`network-infra.md`](../../network-infra.md) (Stage 1, done) — the
  tailnet-wide ACL policy itself is the one piece of that still
  unreviewed.
- **Whether Beszel Hub + Uptime Kuma together actually fit e2-micro's
  1 GB RAM** at this lab's scale (4 managed hosts). Unverified —
  Beszel's hub is a lightweight Go binary, Kuma is Node+SQLite and the
  heavier of the two; combined footprint on 1 GB hasn't been measured.
  This is the load-bearing Assumption for this stage now, in the sense
  [`../README.md#drafts`](../README.md#drafts) means it:
  resolve via a time-boxed spike (deploy both, watch actual RSS) before
  building any Ansible role targeting e2-micro.
- **Gated on [`secret-zero-bootstrap-pattern.md`](secret-zero-bootstrap-pattern.md)
  reaching `decided`, separately from the RAM spike above.** This
  stage is the first time this repo would hand a real credential
  (Beszel's KEY/TOKEN, Kuma's admin state, whatever the Telegram
  wiring below needs) to a host outside physical/network control — see
  that draft's own updated scope section for why that's a materially
  higher blast radius than any on-prem case. No production credential
  goes onto the GCP box until Secret Zero is decided, independent of
  whether the RAM question above resolves favorably. A hardening pass
  for the e2-micro host itself is a separate, not-yet-scoped
  companion gate — low-spec cloud image defaults are not this
  stage's starting assumption.
- e2-micro's Always Free allowance is one instance, restricted to
  `us-west1`/`us-central1`/`us-east1`, with a 1 GB/month egress cap to
  most destinations — worth confirming this lab's expected monitoring
  traffic (push checks, Beszel agent reports) stays under that before
  building against it.
