---
id: ADR-0043
revision: 0
type: adr
title: Host OS hardening baseline
solution: Include the konstruktoid.hardening collection's roles one area at a time from a repo-owned role, each area behind its own Molecule coverage, with unattended security updates first
summary: A deliberate host-level hardening pass (SSH, sysctl, auditd, mandatory access control), not only per-component least privilege.
topic: security-hardening
status: approved
related: [ADR-0004, ADR-0020, ADR-0026, ADR-0047, ADR-0049, ADR-0054, ADR-0058]
---

# 0043. Host OS hardening baseline

## Problem

A deliberate host-level hardening pass (SSH configuration, sysctl, kernel and auditd, mandatory access control), applied to hosts that already run this repo's own roles without silently conflicting with them.

## Context

This repo has individually reasoned hardening choices, such as non-root containers, `docker-socket-proxy` scoping ([ADR 0004](../0004-container-access-to-the-docker-api/revision-000.md)), and least-privilege AppRoles ([ADR 0020](../0020-automation-identity-and-access-scope/revision-000.md), [ADR 0026](../0026-detecting-reads-of-high-value-secrets/revision-000.md)). It has no host-level OS hardening role. The one OS-level setting its roles manage is the `bind9` role's edit of `/etc/systemd/resolved.conf`. No role configures unattended updates, yet [ADR 0054](../0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md) and [ADR 0058](../0058-where-operator-work-runs/revision-000.md) both rely on hosts that patch themselves. `maintenance.yaml` upgrades packages through the `apt` role, reboots when `/var/run/reboot-required` exists, and runs `fwupd`.

**The candidate.** [`konstruktoid/ansible-role-hardening`](https://github.com/konstruktoid/ansible-role-hardening) is a single role that applies every area unless its `manage_*` switch is off. Its README now recommends the maintainer's collection form, [`konstruktoid.hardening`](https://github.com/konstruktoid/ansible-collection-hardening), for continued updates and support. At [`9576750`](https://github.com/konstruktoid/ansible-collection-hardening/tree/9576750a8abef07ff486f00a413573178f646a3f) (version 0.4.0, Apache-2.0) the collection is 44 independent single-purpose roles, with no umbrella role and no top-level playbook; each is configured only through its own variables. It declares Ubuntu resolute (26.04) among its platforms and is pre-1.0. It needs `ansible-core` 2.18 or later, which this repo's lock exceeds, and `ansible.posix`, `community.crypto` and `community.general`; of these the repo pins the first two and not `community.general` (13.0.1 or later).

**What reading it against this repo found.** The collection's own defaults collide with what this repo already does:

- `resolvedconf` templates the whole of `/etc/systemd/resolved.conf` from a template that sets no `DNSStubListener`, while the `bind9` role sets it to `no` on the DNS host so BIND can hold port 53 (`ansible/roles/bind9/tasks/network_conf.yaml`). The two would revert each other.
- `sysctl` defaults include `net.ipv4.ip_forward: 0` and `net.ipv6.conf.all.forwarding: 0`, on hosts where `deploy.yaml` installs Docker.
- `ufw` defaults to `deny`. This repo configures no host firewall, since OPNsense is the perimeter, and how Docker's published ports behave under ufw is not checked.
- `sudo` validates its files with `visudo -cf`, while the fleet runs sudo-rs (`ansible_become_exe: /usr/bin/sudo.ws` in `inventory.yaml`). Whether that validation works against sudo-rs is not checked.
- `lock_root` locks root's password. On managed hosts the maintainer recovers through a VM's console with that host's admin account from the inventory, not root, so this is compatible. The Proxmox node uses root and is not a target of this repo's roles.
- `automatic_updates` installs `unattended-upgrades`, security-only, with no automatic reboot by default, and touches none of the files above.

Each of these is a separate role, so none has to be included in order to include another. A secondary motive is worth naming: this repo carries a portfolio and compliance-demonstration angle ([`nist-800-53-alignment.md`](../../topics/engineering/nist-800-53-alignment.md), a narrative alignment doc, not a compliance artifact), and a recognizable CIS-shaped baseline has legibility value distinct from its security value.

## Decision

- **Source.** The `konstruktoid.hardening` collection, pinned to an exact version in `ansible/requirements.yml` together with its `community.general` dependency. Not the older single role.
- **Shape.** A repo-owned role includes `konstruktoid.hardening.<area>` roles from an explicit allow-list. No area is included by default, and the collection is never applied whole.
- **Adding an area.** One change per area. It includes the role, sets the variables this repo needs, adds or extends a Molecule scenario that asserts the area's effect and passes the idempotence check, and states what the area overrides of this repo's own roles. An area with a collision listed above is not added until the same change resolves it.
- **First area: unattended security updates** (`automatic_updates`): security-only, no automatic reboot, on every host in scope. Reboots and firmware stay in `maintenance.yaml` (`apt` and `fwupd`).
- **Scope.** Every on-prem host this repo configures, whether or not it is in `managed_hosts`: the managed hosts, `network_infra`, the operator host, the CD agent, and the coding-agent host. The off-site hosts get a separate profile later, after [ADR 0047](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md).
- **Later areas.** Which areas follow and in what order is a project decision.

## Alternatives considered

- **The single `ansible-role-hardening` role.** Its maintainer recommends the collection, and its design applies every area unless switched off, so each collision above would be an override carried against upstream's defaults.
- **The collection applied whole, with overrides.** Each collision becomes an override that tracks someone else's defaults, and a release that changes a default changes every host silently.
- **A hand-written subset in this repo.** Where the collection has a role for an area, writing it again duplicates upstream's maintenance. A hand-written area remains possible where no role fits, each as its own decision.
- **The DevSec Linux Baseline.** Named earlier and not evaluated. The per-area shape answers the collision risk the comparison was for.
- **The shell-script `konstruktoid/hardening`.** Host configuration here is Ansible-only ([ADR 0001](../0001-host-configuration-reproducible-from-repo/revision-000.md)).

## Consequences

- The dependency is pre-1.0, so an exact pin and a bump that reruns every included area's Molecule scenario are the control against a changed default.
- `ansible/requirements.yml` gains `konstruktoid.hardening` and `community.general`.
- Coverage is thin on purpose. Until areas are added, hosts have only unattended updates, and the CIS-shaped legibility grows with the areas, not at once.
- The first area satisfies the unattended-update reliance of ADR 0054 and ADR 0058. [`coding-agent-host.md`](../../projects/coding-agent-host.md) still lists unattended updates inside its own role and should consume this area once a baseline project exists.
- The Proxmox node is outside the baseline.

## Invariants

- No hardening role runs on a host unless its area is in the allow-list.
- Every allow-listed area has a Molecule scenario that asserts its effect.
- No two roles manage the same file or setting without the change that adds the second resolving it.

## Non-goals

- The Proxmox node itself.
- The off-site hosts' profile, and the resource cost of areas such as `auditd` and `aide` on the small off-site VM ([ADR 0049](../0049-monitoring-that-survives-loss-of-the-site/revision-000.md)); that is assessed when the profile is written.
- Which areas follow the first, and their order.

## Validation

Each area's Molecule scenario asserts its effect and idempotence. For unattended updates the effect is the effective apt configuration, not the drop-in files: with security-only updates and no automatic reboot the role's drop-in holds only the unused-package cleanup lines, and those two properties come from Ubuntu's stock configuration plus the role adding no `-updates` origin and no reboot line. The scenario therefore reads `apt-config dump` and asserts the periodic-update lines are set, no allowed origin is an `-updates` pocket, and no automatic reboot is set.

## Reconsideration triggers

- The collection is abandoned, or a release changes the defaults of an included area in a way that breaks hosts.
- A benchmark assertion (CIS or STIG compliance) is wanted, which would favor applying the collection whole.
- The off-site hosts need a baseline before the on-prem areas are far along.
