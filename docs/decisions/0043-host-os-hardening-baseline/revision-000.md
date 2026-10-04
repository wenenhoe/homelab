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

**What reading the role against this repo found.** At
[`konstruktoid/ansible-role-hardening@b27b739`](https://github.com/konstruktoid/ansible-role-hardening/tree/b27b73944ff8ea33c266857f5f781c82288be702),
the conflicts are concrete:

- `manage_resolved` is true by default, and `tasks/resolvedconf.yml`
  templates the whole of `/etc/systemd/resolved.conf` from a template
  that sets no `DNSStubListener`. The `bind9` role sets that line to
  `no` on the DNS host (`ansible/roles/bind9/tasks/network_conf.yaml`)
  so BIND can hold port 53, so the two roles revert each other.
- The default sysctl settings include `net.ipv4.ip_forward: 0` and
  `net.ipv6.conf.all.forwarding: 0`, on hosts where `deploy.yaml`
  installs Docker.
- `manage_ufw` is true by default and the ufw tasks set a default of
  `deny`. This repo configures no host firewall, since OPNsense is the
  perimeter, and how Docker's published ports behave under ufw is not
  checked.
- `manage_sudo` is true by default and its tasks validate with
  `visudo -cf`, while the fleet runs sudo-rs (`ansible_become_exe:
  /usr/bin/sudo.ws` in `inventory.yaml`). Whether that validation works
  against sudo-rs is not checked.
- `disable_root_account` is true by default and locks root's password,
  which bears on the console break-glass path of
  [ADR 0058](../0058-where-operator-work-runs/revision-000.md).
- `automatic_updates` is enabled by default, security-only, and
  installs `unattended-upgrades` on Debian-family hosts. No role here
  configures unattended updates, yet
  [ADR 0054](../0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md)
  and [ADR 0058](../0058-where-operator-work-runs/revision-000.md) both
  rely on hosts that patch themselves, and
  [`coding-agent-host.md`](../../projects/coding-agent-host.md) plans it
  inside its own role.

Each is a role default, so none rules the role out alone. The choice is
between keeping one override per conflict and writing the few settings
wanted directly.

There's also a secondary, non-technical motive worth naming honestly:
this repo already carries a portfolio/compliance-demonstration angle
([`nist-800-53-alignment.md`](../../topics/engineering/nist-800-53-alignment.md), a
narrative alignment doc, not a compliance artifact). A recognizable
baseline (CIS-shaped) has legibility value for that purpose distinct
from its actual security value — worth naming as a factor, not
pretending it's purely a security decision.

## Decision

Not yet — no comparison has been run. This draft exists to hold the
question and the real alternatives, not to pick one.

## Assumptions

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
