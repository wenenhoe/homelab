---
id: ADR-0042
revision: 0
type: adr
title: Monitoring that survives loss of the monitoring host
solution: Bring the Tailscale subnet router under management, then run monitoring on a dedicated on-prem host
summary: Beszel and Kuma keep running, and alerting, when the host they run on fails.
topic: monitoring-alerting
status: approved
related: [ADR-0010, ADR-0049]
---

# Monitoring host isolation — bring VM 202 under management, then a dedicated on-prem monitoring host

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
infrastructure that breaks silently because nothing tracks it.

This record covers a failure of `security` as a host or process. The case it can't solve, the whole site going dark, is [ADR 0049](../0049-monitoring-that-survives-loss-of-the-site/revision-000.md).

## Decision

Two stages, in this order:

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

## Not yet done

- VM 202's current configuration is now read and recorded in
  [`network-infra.md`](../../network-infra.md) (Stage 1, done) — the
  tailnet-wide ACL policy itself is the one piece of that still
  unreviewed.
