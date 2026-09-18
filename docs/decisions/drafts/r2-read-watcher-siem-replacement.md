---
id: DRAFT-r2-read-watcher-siem-replacement
title: "Replace r2_read_watcher.py with a proper audit pipeline (e.g. Wazuh)?"
type: draft-adr
status: draft
---

# Replace r2_read_watcher.py with a proper audit pipeline (e.g. Wazuh)?

**Status:** Draft — leaning toward a placement (see Decision below);
CPU fit and ARM64 support still unverified, no spike run yet

## Context

`docker/openbao/watcher/r2_read_watcher.py` (ADR 0026) is a
purpose-built Python watcher for exactly one thing: alerting on reads
of the R2 admin token. Confirmed: no SIEM/audit-log tooling (Wazuh or
otherwise) exists anywhere in this repo today — this is a genuinely
new direction, not a gap in an existing setup.

The instinct is reasonable on its face: a single-purpose watcher
doesn't generalize, and this repo already has a recognizable pattern —
narrow, independently-written alerting code showing up in more than
one place (this watcher, `check_freshness.py`'s Telegram call,
`telegram_notify`/`telegram_topic_pins` roles, `uptime_kuma_push`) —
similar in shape to the OpenBao-client duplication already found this
session, just for alerting instead of secrets access.

## Evaluated: resource budget

[ADR 0035](../0035-not-adopting-kubernetes-on-current-hardware.md)'s
research answers the first "not yet evaluated" item directly, so it's
folded in here rather than left open:

- **OCI's Always Free tier can't run Wazuh at all.** Oracle's
  documented Ampere A1 Always Free allowance was cut in 2026 to 2
  OCPU/12 GB (down from the 4 OCPU/24 GB figure still widely quoted).
  Wazuh's own docs list 4 cores/8 GB RAM/50 GB disk as the *minimum*
  for a single-node stack (manager+indexer+dashboard) — before adding
  the Beszel/Kuma processes
  [`off-site-monitoring-independence-not-oci-tailscale-tunnel.md`](off-site-monitoring-independence-not-oci-tailscale-tunnel.md)
  already plans for that box. Wazuh alone is double the free OCPU
  budget. Single-node Wazuh's Docker docs also only listed AMD64 until
  recently — ARM64 (what Ampere A1 actually is) only appears as
  supported starting in the 5.0-beta docs, so even with the OCPU/RAM
  budget this would need its own compatibility check, not assumed.
- **The single Proxmox host doesn't have comfortable room either.**
  [ADR 0035](../0035-not-adopting-kubernetes-on-current-hardware.md)'s
  hardware accounting (6-core i5-9400, 32 GB RAM, ~18 GB headroom
  after planned VM sizing) means an on-prem Wazuh VM would eat a large
  fraction of the host's remaining budget for one service.
- **The single Proxmox host would actually clear Wazuh's documented
  minimum**, and is worth naming since it's the one option that
  doesn't require guessing: a dedicated 4 vCPU/8 GB/50 GB VM fits
  inside the ~18 GB RAM headroom [ADR 0035](../0035-not-adopting-kubernetes-on-current-hardware.md)
  already accounts for, on x86 (no ARM64 compatibility question), on
  1 TB of NVMe ([`../../../README.md#hardware`](../../../README.md#hardware)).
  The cost isn't resources
  — it's CPU oversubscription (pushes allocated vCPU from 12 to 16
  against 6 physical cores) and putting a new always-on service on the
  same consumer hardware as everything else in this lab.
- **Conclusion, revised now that Beszel/Kuma are moving to GCP e2-micro
  instead of OCI** (see
  [`off-site-monitoring-independence-not-oci-tailscale-tunnel.md`](off-site-monitoring-independence-not-oci-tailscale-tunnel.md)):
  OCI's Ampere A1 free tier, if handed to Wazuh alone rather than
  shared with Beszel/Kuma, clears the *RAM* minimum (12 GB vs. the
  documented 8 GB floor) but still falls short on *CPU* (2 OCPU vs. the
  documented 4-core floor). That's a real, named gap, not one resolved
  by freeing up the box — see Decision below for why it's still the
  chosen direction, and Assumptions for what's unverified about it.

## Decision (leaning, not yet verified)

Run Wazuh on OCI's Ampere A1 Always Free instance, dedicated — not
shared with Beszel/Kuma, which relocate to GCP e2-micro instead (that
relocation is the other draft's decision, not this one, but this
draft's plan depends on it landing).

This is a preference, not a resilience requirement, and that
distinction matters: Beszel/Kuma have to survive a whole-site outage
because detecting the outage *is* their job — that's what
off-site-monitoring's project is solving. Wazuh's job (host/log
security telemetry) only has value while the site is up in the first
place; a site-wide outage makes Wazuh's own reachability moot the same
way it makes everything else moot. So Wazuh has no structural
requirement to live off-prem. Choosing OCI over the Proxmox host here
is purely about not adding a new always-on service, oversubscribed
CPU and all, to the one piece of consumer hardware this whole lab
already depends on — not about site independence.

## Assumptions

- **Wazuh runs adequately on 2 OCPU** — half the documented 4-core
  single-node minimum. Unverified either way; the "minimum" figure in
  Wazuh's own docs may be conservative for a homelab's actual host
  count and log volume, or may not be. Breaks the Decision above if
  Wazuh genuinely can't function on 2 OCPU. Resolve via a time-boxed,
  throwaway spike: single-node Wazuh on an actual 2 OCPU/12 GB Ampere
  A1 instance, pointed at this lab's real host count, before any
  Ansible role gets written for it.
- **Wazuh's Docker images run on ARM64** outside the 5.0-beta docs.
  Unverified. Check in the same spike as above, before committing.
- **GCP e2-micro (1 GB RAM) actually carries Beszel Hub + Uptime Kuma
  together** at this lab's scale. This is the other draft's Assumption
  to resolve, not this one's — but this draft's OCI-dedicated plan
  depends on it: if e2-micro can't carry both, OCI doesn't get freed
  up for Wazuh alone and this Decision needs revisiting.
- **Gated on [`secret-zero-bootstrap-pattern.md`](secret-zero-bootstrap-pattern.md)
  reaching `decided`**, same as the off-site-monitoring draft above and
  for the same reason: OCI is a host outside physical/network control,
  and this is the first time this repo would hand it a real credential.
  No production credential goes onto the OCI box until that's decided
  — independent of the CPU/ARM64 spike above. A hardening pass for
  this specific host is a separate, not-yet-scoped companion gate.

## A conflict this draft creates, not previously connected

If any log-shipping/aggregation tool — Wazuh or otherwise — is ever
adopted, it collides with a named, load-bearing assumption in
[ADR 0026](../0026-openbao-audit-device-and-r2-per-read-watcher.md):
that OpenBao's plaintext audit log stays contained to `security`
specifically *because* "no compose service in this repo ships logs
anywhere today." ADR 0026's Consequences section says this explicitly
— "revisit the day one is added." A SIEM/log-aggregation pipeline
**is** that day, and Wazuh's placement (OCI vs. on-prem, above)
doesn't change that — the log is contained to `security` today either
way, and shipping it anywhere is what breaks the containment, not
which host receives it.

What actually leaves `security` if this happens is worth stating from
ADR 0026 itself rather than re-guessing it: every Vault operation's
`request.path`, policy name, entity ID, operation, and timestamp is
**plaintext**; secret values and tokens stay **HMAC'd**, not plaintext.
ADR 0026's own threat model calls the plaintext side "real
reconnaissance value" — a full map of every credential's existence,
naming, and access pattern — while noting it's bounded as long as it
stays on `security`. So "doesn't contain much sensitive information"
undersells the plaintext side and oversells the HMAC'd side backwards
— values are the part that's protected; paths/policies/timing are not,
and that's the part a SIEM would actually be aggregating. This doesn't
resolve the question, it just means resolving it can't lean on the
audit log being low-value — it has to weigh that named recon value
against whatever detection benefit shipping it into Wazuh would
provide. Still open, not decided by this conversation.

Before this draft's `check_freshness.py`/`telegram_notify`/
`uptime_kuma_push` question (below) gets resolved in either direction,
revisiting ADR 0026's containment story has to be part of the same
decision — shipping OpenBao's audit log into a SIEM changes what "the
log stays on `security`" means, even if the sources that actually get
wired up turn out to be narrower than that.

## Not yet evaluated

- Whether ADR 0026's containment story (see above — plaintext
  paths/policies/entity IDs/timestamps, HMAC'd values) gets revisited
  as its own decision first, or folded into whatever this draft
  eventually decides — not resolved either way yet.
- What `r2_read_watcher.py`'s specific detection (a narrow, low-volume,
  high-signal credential-read alert) would need to look like once
  reimplemented as a generic SIEM rule, and whether that's actually as
  reliable as the current purpose-built check.
- Which of `check_freshness.py`, `telegram_notify`, `telegram_topic_pins`,
  and `uptime_kuma_push` would actually feed into it, versus staying
  separate because they're already fine — "what should hook up to
  Wazuh" is the real open question, not "replace everything with it."

## Why this is its own draft, not a stage of an existing project

This isn't a library swap like most of the drafts in this repo — it's
a new piece of infrastructure with its own resource footprint,
operational surface, and maintenance burden. It doesn't belong under
[ADR 0030](../0030-openbao-hvac-paramiko-clients.md) (that's about
which Python client talks to OpenBao, not what watches for suspicious
access) or
`ansible-collections-audit.md` (that's about existing roles' task
shape, not new infrastructure). Needs its own scoping pass before it's
more than a name on a list.
