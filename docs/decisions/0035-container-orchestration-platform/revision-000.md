---
id: ADR-0035
revision: 0
type: adr
title: Container orchestration platform
solution: Docker Compose with Ansible; no Kubernetes for now
summary: Whether a single-host homelab runs an orchestrator, given the resource cost on 6 cores and 32 GB.
topic: deployment-platform
status: accepted
related: [ADR-0005]
---

# 0035. Not adopting Kubernetes on current hardware

**Status:** Accepted

## Context

Everything in this repo runs on one Proxmox host: 6-core i5-9400 (6
physical cores, no hyperthreading), 32 GB RAM, NVMe for VM disks, a
separate HDD for backups only (`../../../README.md#hardware`).
[`vm-provisioning.md`'s default sizing table](../../vm-provisioning.md#ubuntu-vms)
— a provisional planning baseline, not measured production usage —
already accounts for most of that budget: 12 vCPU and 14 GB RAM across
OPNsense, `services`, `security`, `play`, and `storage`, leaving
roughly 18 GB RAM of headroom. `services` and `security` alone carry
20 apps' worth of `docker/` compose stacks inside a combined 4 GB.

Kubernetes adoption was raised with two specific angles: whether a
single Proxmox node could cluster with an OCI Ampere A1 free-tier
instance for a second node, and whether that changes VM sizing or
security posture. (Separately, whether OCI's compute budget can carry
an expanded monitoring stack — Prometheus+Grafana, Wazuh — is its own,
already-tracked question; see
[`0042-monitoring-that-survives-loss-of-the-homelab/revision-000.md`](../0042-monitoring-that-survives-loss-of-the-homelab/revision-000.md)
and
[`0045-security-event-collection-and-alerting/revision-000.md`](../0045-security-event-collection-and-alerting/revision-000.md).
It's unaffected by this decision either way.)

Three facts make the trade-off concrete rather than generic:

- **Per-node overhead is the actual cost.** Any Kubernetes node — even
  a minimal k3s agent — carries a fixed baseline (kubelet, container
  runtime, CNI) before it schedules a single workload. Splitting
  today's two flat VMs (`services`+`security`, 4 vCPU/4 GB combined)
  into a control-plane-plus-worker topology pays that overhead
  multiple times over, on a host that's already dense.
- **An OCI node can't sit in the control plane.** etcd (or k3s's
  embedded equivalent) is latency-sensitive consensus, expecting
  single-digit-millisecond round trips between members — a
  well-established distributed-systems constraint, not something
  specific to this lab that needs a spike to confirm. An OCI instance,
  reached over the existing Tailscale subnet router, is a WAN hop.
  It could join only as a plain worker for latency-tolerant workloads
  — a materially smaller claim than "cluster in the free OCI box" —
  and doing even that would overload the OCI host with a second role
  the off-site-monitoring draft deliberately keeps single-purpose.
- **The attack surface grows for real.** Today's surface is Caddy +
  Tinyauth + TLS in front of Compose apps, matching this repo's
  existing least-privilege, non-root, minimal-caps posture. Kubernetes
  adds an API server, RBAC to actually configure, NetworkPolicies (or
  a flat-by-default network), and a CNI to patch — real, ongoing
  surface for a workload profile (20 static apps, one operator) that
  isn't exhibiting the problems Kubernetes exists to solve: workload
  variance, horizontal autoscaling, or rolling multi-node deploys.

## Decision

Do not adopt Kubernetes now. Stay on Docker Compose + Ansible for the
single-Proxmox-host setup this repo already runs. Do not cluster the
OCI monitoring host into any future Kubernetes control plane; if
Kubernetes is ever adopted, OCI's role stays at most a latency-tolerant
worker, chosen deliberately at that time — not inherited from "there's
already an OCI box available."

Revisit only if a real trigger shows up, not on a schedule:

- Workload variance appears that Compose genuinely can't express (a
  specific app needing to scale horizontally — not "more capacity" in
  general).
- The single-Proxmox-host constraint itself changes — new/expanded
  hardware — such that per-node overhead stops being the binding cost.
- Rolling, zero-downtime multi-host deploys become a real requirement
  rather than a nice-to-have.

## Consequences

- `vm-provisioning.md`'s sizing table stays flat per-app VM sizing;
  no Tofu work should assume a Kubernetes node topology.
- The OCI monitoring host stays single-purpose, per the off-site-
  monitoring draft's existing design — no expectation it doubles as
  compute for anything else.
- No CI, deploy, or role changes follow from this decision — it's a
  documented "don't build," not a migration.
- If revisited later, re-check this ADR's hardware numbers first
  rather than assume they still hold — a different or expanded
  Proxmox host changes the per-node-overhead math this decision rests
  on. Supersede this ADR at that point rather than editing it in place.
