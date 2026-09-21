---
id: ADR-0039
revision: 0
type: adr
title: Intrusion detection scope
solution: 'Undecided: CrowdSec at the perimeter only, or with per-VM agents'
summary: Whether detection lives only on the OPNsense perimeter or also on each VM, without inspecting the lab's own TLS.
topic: security-hardening
status: working
---

# CrowdSec: perimeter-only on OPNsense, or perimeter plus per-VM agents?

## Context

No IDS/IPS exists anywhere in this repo today. The stated constraint
going in: something that works without inline traffic inspection (no
MITM of this lab's own TLS) — which rules out most inline-proxy-style
IPS designs and points toward
[CrowdSec](https://www.crowdsec.net/): local, log-based detection per
node, decisions shared through a community/local API rather than
sitting in the traffic path itself. OPNsense has a maintained CrowdSec
plugin (parses firewall/WAN logs, applies blocks via pf), which fits
this lab's existing perimeter directly.

**The real open question is scope, not tooling** — two genuinely
different footprints:

- **Perimeter-only**: CrowdSec runs on OPNsense alone, parsing its own
  firewall/WAN logs. Catches network-level scanning/brute-force
  patterns hitting the edge; blind to anything that looks fine at the
  firewall but is malicious at the application layer (e.g. valid HTTP
  requests to Caddy that are themselves the attack).
- **Perimeter + per-VM agents**: every managed host also runs a
  CrowdSec agent reading its own auth/app logs (SSH, Caddy access
  logs, container logs), feeding local detections back to a central
  LAPI. Much richer coverage, real per-host resource cost, and a new
  fleet-wide credential (each agent's LAPI key) — another instance of
  the Secret Zero question
  ([`../0047-first-credential-bootstrap-for-automated-processes/revision-000.md`](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md)),
  not a separate problem.

A blocker worth naming plainly rather than discovering mid-build:
[`vm-provisioning.md`](../../vm-provisioning.md) already documents
OPNsense's day-2 config (installing plugins, applying settings via its
config API) as **Phase 2, not yet built** — today's OPNsense
provisioning is Phase 1 only (VM shell + manual install). Perimeter
CrowdSec on OPNsense can't be Ansible/Tofu-automated yet for the same
reason nothing else on OPNsense can be; it would start as a manual
install, same category as OPNsense itself today, not a gap specific to
CrowdSec.

## Decision

Not yet — this draft exists to hold the scope question and the
Phase 2 dependency, not to answer them.

## Assumptions

- **Perimeter-only vs. perimeter+agents** — genuinely unresolved,
  named above; not a spike question so much as a "how much visibility
  is actually wanted" decision once someone's ready to make it.
- **Whether OPNsense's CrowdSec plugin is usable at all before
  `vm-provisioning.md`'s Phase 2 lands.** Likely yes as a one-off
  manual install (same as OPNsense's own current bootstrap), but
  running it unmanaged is itself a small instance of the
  unmanaged-but-load-bearing-infrastructure pattern this repo has
  already flagged elsewhere (VM 202 before Stage 1 of
  off-site-monitoring). Not confirmed either way.
- **Per-VM agent scope, if chosen, needs its own Secret Zero answer**
  for each agent's LAPI key — genuinely the same open question as
  [`../0047-first-credential-bootstrap-for-automated-processes/revision-000.md`](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md),
  not a new one to solve independently.

## Consequences

None yet — nothing has been decided or built against this draft.
