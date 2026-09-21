---
id: ADR-0043
revision: 0
type: adr
title: Host OS hardening baseline
solution: 'Undecided: a third-party baseline, or a hand-picked subset in this repo''s own roles'
summary: A deliberate host-level hardening pass (SSH, sysctl, auditd, mandatory access control), not only per-component least privilege.
topic: security-hardening
status: working
related: [ADR-0004, ADR-0020, ADR-0026]
---

# OS hardening: adopt a third-party baseline, or a hand-picked subset via this repo's own roles?

## Context

This repo has plenty of individually-reasoned hardening choices —
non-root containers, `docker-socket-proxy` scoping ([ADR 0004](../0004-container-access-to-the-docker-api/revision-000.md)),
least-privilege AppRoles ([ADR 0020](../0020-automation-identity-and-access-scope/revision-000.md),
[0026](../0026-detecting-reads-of-high-value-secrets/revision-000.md)) — but
no single, deliberate **host-level OS hardening pass** (SSH config,
sysctl, kernel/auditd, mandatory access control, CIS/STIG-shaped
baseline). Two candidates raised:
[konstruktoid/hardening](https://github.com/konstruktoid/hardening)
(a shell-script baseline) and its Ansible equivalent
[konstruktoid/ansible-role-hardening](https://github.com/konstruktoid/ansible-role-hardening),
CIS-influenced. Other options exist too — the DevSec/Dev-Sec Linux
Baseline role, or hand-picking a narrow subset directly into this
repo's own roles instead of adopting someone else's role wholesale.

This has become more load-bearing than a nice-to-have: both offsite
drafts ([`../0049-monitoring-that-survives-loss-of-the-site/revision-000.md`](../0049-monitoring-that-survives-loss-of-the-site/revision-000.md),
[`../0045-security-event-collection-and-alerting/revision-000.md`](../0045-security-event-collection-and-alerting/revision-000.md))
now name a hardening pass as a companion gate to Secret Zero, precisely
because a GCP/OCI free-tier instance starts from a cloud provider's
default image, not a baseline this repo has ever defined.

**The real risk, named plainly:** adopting a third-party role
wholesale on hosts already managed by this repo's own Ansible risks
silent conflict — SSH config, sysctl values, or firewall state that
`konstruktoid/ansible-role-hardening` sets one way and something this
repo's own roles (or Caddy, Tinyauth, `docker`) expect set another way,
discovered only when something breaks, not declared anywhere. That's
the actual comparison this draft needs to do, not "which name is more
popular."

There's also a secondary, non-technical motive worth naming honestly:
this repo already carries a portfolio/compliance-demonstration angle
([`nist-800-53-alignment.md`](../../nist-800-53-alignment.md), a
narrative alignment doc, not a compliance artifact). A recognizable
baseline (CIS-shaped) has legibility value for that purpose distinct
from its actual security value — worth naming as a factor, not
pretending it's purely a security decision.

## Decision

Not yet — no comparison has been run. This draft exists to hold the
question and the real alternatives, not to pick one.

## Assumptions

- **Whether `konstruktoid/ansible-role-hardening`'s defaults conflict
  with anything this repo's own roles already set** on the hosts it'd
  run against. Not yet checked — no spike has read that role's task
  list against this repo's own `ansible/roles/*` to look for overlap
  (SSH, sysctl, ufw/nftables, auditd). Breaks a "just add the role"
  plan if real conflicts exist; likely resolvable with `--tags`/vars
  to disable conflicting pieces, but that's a claim to verify, not
  assume.
- **Whether hardening applies uniformly to every host, or differently
  to the offsite GCP/OCI boxes vs. the on-prem fleet.** An offsite,
  low-spec free-tier VM and an on-prem VM behind OPNsense have
  different actual attack surfaces (public IP exposure being the
  biggest difference) — a single baseline applied identically to both
  may be either insufficient for one or wasteful for the other. Not
  evaluated yet.
- **Resource cost on e2-micro specifically** — some baselines add
  auditd/aide-style continuous scanning that costs real CPU/RAM on a
  1 GB box already tight per
  [`../0049-monitoring-that-survives-loss-of-the-site/revision-000.md`](../0049-monitoring-that-survives-loss-of-the-site/revision-000.md).
  Not checked.

## Consequences

None yet — nothing has been decided or built against this draft.
