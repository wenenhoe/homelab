---
id: ADR-0049
revision: 0
type: adr
title: Monitoring that survives loss of the site
short: Site-loss monitoring
solution: Relocate monitoring to a GCP e2-micro, reached by extending VM 202's Tailscale subnet route
summary: Something outside the site notices when the whole homelab or its connectivity goes down.
topic: monitoring-alerting
status: working
related: [ADR-0010, ADR-0042, ADR-0047, ADR-0073]
---

# 0049. Monitoring that survives loss of the site

## Context

[ADR 0042 (Monitoring host loss)](../0042-monitoring-that-survives-loss-of-the-homelab/revision-000.md) describes the gap (Beszel and Kuma both live entirely on `security`) and isolates monitoring from that host. It doesn't solve the whole homelab, or its connectivity, going down: structurally the same threat model [ADR 0010 (Offsite copy deletion)](../0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md) already solved for backups.

It also
means the actual mechanism needed for an eventual cloud-hosted monitor
to reach the 4 managed hosts already exists — no new tunnel technology,
just extending an existing Tailscale subnet route to a new node and
bringing the router itself under management.

[ADR 0047 (First-credential bootstrap)](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md) is approved, so the GCP host holds no OpenBao identity and receives only the secrets its own role needs, pushed by Ansible. A compromise of it exposes those secrets and a tailnet route back into the lab.

## Decision

**Relocate to GCP's e2-micro Always Free instance**, reached by
extending the same Tailscale subnet route VM 202 already provides
(from [ADR 0042 (Monitoring host loss)](../0042-monitoring-that-survives-loss-of-the-homelab/revision-000.md)'s Stage 1) to the new GCP node — this is the actual
site-independence win, and it costs no new tunnel technology, only
the actual work of adding GCP as a route destination (VM 202
doesn't reach it for free just because the mechanism already
exists elsewhere). OCI was the original target for this stage;
it's now earmarked instead for a dedicated, on-prem-adjacent Wazuh
instance — see
[`../0045-security-event-collection-and-alerting/revision-000.md`](../0045-security-event-collection-and-alerting/revision-000.md)
— which is why this stage moved to a different provider rather than
sharing OCI with it.

## Alternatives considered

- **Open:** Whether this relocates the *entire* Beszel+Kuma stack, or only a
  minimal independent heartbeat (one Kuma monitor watching "is the
  homelab reachable from outside at all") — the fuller stack gives
  richer visibility but means bootstrapping Beszel's KEY/TOKEN and
  Kuma's admin account a second time, both documented as manual,
  DB-resident, and not template-able ahead of first boot. This
  question matters more now than it did against OCI: e2-micro's 1 GB
  RAM is the tighter of the two boxes this stage ever considered.

## Assumptions

- **Claim:** Beszel Hub and Uptime Kuma together fit e2-micro's 1 GB RAM at this lab's scale (4 managed hosts).
  **Breaks if wrong:** only a minimal heartbeat monitor can be relocated, not the full stack.
  **Checked by:** a time-boxed spike (deploy both, watch actual RSS) before building any Ansible role targeting e2-micro. Beszel's hub is a lightweight Go binary and Kuma is Node+SQLite, the heavier of the two; the combined footprint on 1 GB hasn't been measured.
- **Claim:** this lab's monitoring traffic (push checks, Beszel agent reports) stays under e2-micro's Always Free egress cap: one instance, in `us-west1`/`us-central1`/`us-east1`, with a 1 GB/month cap to most destinations.
  **Breaks if wrong:** the free-tier instance can't carry the monitoring load.
  **Checked by:** estimating the expected traffic before building against it.
- **Claim:** a hardening pass for the e2-micro host itself exists before it holds credentials; low-spec cloud image defaults are not this stage's starting assumption.
  **Breaks if wrong:** the same blast radius as above, on a host whose defaults nobody reviewed.
  **Checked by:** scoping that pass; it is a separate, not-yet-scoped companion gate.
- **Claim:** the instance can reach Telegram and the tailnet through an ephemeral external address with all ingress denied, at no charge on the free tier.
  **Breaks if wrong:** an address or NAT charge applies, or the instance needs a reserved address, and the free-tier claim above no longer holds.
  **Checked by:** the billing view during the spike in [`gcp-e2-micro-provisioning.md`](../../projects/gcp-e2-micro-provisioning.md); Google's free-tier page states the e2-micro's external address is not charged, which the spike confirms rather than assumes.
- **Claim:** the identity that provisions the instance is settled by [ADR 0073 (Off-site cloud auth)](../0073-how-provisioning-authenticates-to-the-off-site-cloud/revision-000.md) before any provisioning code is built.
  **Breaks if wrong:** the first off-site build would fix a standing key or token on the maintainer side by default.
  **Checked by:** ADR 0073 reaching `approved`.
