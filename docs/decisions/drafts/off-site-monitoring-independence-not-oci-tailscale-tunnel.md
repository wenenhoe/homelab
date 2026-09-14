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
[ADR 0010](../0010-cloud-sync-copy-not-sync.md) already solved for
backups, just never applied to monitoring.

Tailscale isn't absent from the
environment, only from the repo. **VM 202 already exists and already
runs as a subnet router**, routing Tailscale clients to the 4 managed
hosts — it's just not under Ansible/repo management yet. That's a
real gap in its own right, the same category as the scattered OpenBao
clients this repo has elsewhere: unmanaged-but-load-bearing
infrastructure that breaks silently because nothing tracks it. It also
means the actual mechanism needed for an eventual OCI-hosted monitor
to reach the 4 managed hosts already exists — no new tunnel technology
required, just bringing existing infrastructure under management and
extending its use.

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
3. **Relocate to OCI**, reached over the same already-existing
   Tailscale subnet router from Stage 1 — this is the actual
   site-independence win, and it costs no new network technology since
   VM 202 already provides the connectivity primitive.

## Not yet done

- Whether Stage 3 relocates the *entire* Beszel+Kuma stack, or only a
  minimal independent heartbeat (one Kuma monitor watching "is the
  homelab reachable from outside at all") — the fuller stack gives
  richer visibility but means bootstrapping Beszel's KEY/TOKEN and
  Kuma's admin account a second time, both documented as manual,
  DB-resident, and not template-able ahead of first boot.
- VM 202's current configuration is now read and recorded in
  [`network-infra.md`](../../network-infra.md) (Stage 1, done) — the
  tailnet-wide ACL policy itself is the one piece of that still
  unreviewed.
- Whether OCI compute is already available/budgeted for Stage 3, or is
  new spend — OCI's current use in this repo is object storage/IAM,
  not compute.
