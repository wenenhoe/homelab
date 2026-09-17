---
id: DRAFT-r2-read-watcher-siem-replacement
title: "Replace r2_read_watcher.py with a proper audit pipeline (e.g. Wazuh)?"
type: draft-adr
status: draft
---

# Replace r2_read_watcher.py with a proper audit pipeline (e.g. Wazuh)?

**Status:** Draft — exploratory, not scoped for building yet

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
- **Conclusion this draft can now state plainly:** Wazuh specifically
  doesn't fit this lab's free/existing compute anywhere. Adopting it
  at all means either paid OCI compute (real ongoing cost) or hardware
  expansion — not a decision to make as a byproduct of "we already
  have an OCI box" or "the Proxmox host has some room."

## A conflict this draft creates, not previously connected

If any log-shipping/aggregation tool — Wazuh or otherwise — is ever
adopted, it collides with a named, load-bearing assumption in
[ADR 0026](../0026-openbao-audit-device-and-r2-per-read-watcher.md):
that OpenBao's plaintext audit log stays contained to `security`
specifically *because* "no compose service in this repo ships logs
anywhere today." ADR 0026's Consequences section says this explicitly
— "revisit the day one is added." A SIEM/log-aggregation pipeline
**is** that day. Before this draft's `check_freshness.py`/
`telegram_notify`/`uptime_kuma_push` question (below) gets resolved in
either direction, revisiting ADR 0026's containment story has to be
part of the same decision — shipping OpenBao's audit log into a SIEM
changes what "the log stays on `security`" means, even if the sources
that actually get wired up turn out to be narrower than that.

## Not yet evaluated

- Whether ADR 0026's audit-log containment story (see above) gets
  revisited as its own decision first, or folded into whatever this
  draft eventually decides — not resolved either way yet.
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
