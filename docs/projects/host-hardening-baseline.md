---
id: PROJ-host-hardening-baseline
title: "Host Hardening Baseline"
type: project
status: building
blocked: false
summary: "A repo-owned role that includes the hardening collection's areas from an allow-list, starting with unattended security updates on every patched host."
decision: ADR-0043/0
---

# Host Hardening Baseline

Builds the mechanism [ADR 0043](../decisions/0043-host-os-hardening-baseline/revision-000.md) chose and its first area. Staged because pinning the collection, adding one area with its test, and applying it to the fleet are independent changes with different risks.

## Scope

A pinned `konstruktoid.hardening` collection, a repo-owned `host_hardening` role that includes only allow-listed areas, the `automatic_updates` area as the first, and its application to every host in `patched_hosts`. Not in scope: any later area, the off-site hosts, and the Proxmox node (all per the decision's non-goals).

## Decision

Implements [ADR 0043](../decisions/0043-host-os-hardening-baseline/revision-000.md), `approved`. Hosts in their own inventory groups (the operator host, the CD agent, the coding-agent host) include the role from their own builds; see Open items.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Pin `konstruktoid.hardening` (exact version) and `community.general` (13.0.1 or later) in `ansible/requirements.yml`, and add the `host_hardening` role with an empty allow-list | In progress | Both collections install in CI, and the role converges as a no-op and passes idempotence |
| 2 | `automatic_updates` area: security-only, no automatic reboot, with a Molecule scenario; the scenario installs collections from `ansible/roles/molecule_helpers/requirements.yml`, so both pins go there too | Not started | The scenario asserts the `20auto-upgrades` and `52unattended-upgrades-local` drop-ins carry security-only updates and no automatic reboot, passes idempotence, and appears in the scenario matrix |
| 3 | Apply the role to every host in `patched_hosts` | Not started | After a run, each such host has the drop-ins, and `maintenance.yaml` still upgrades and reboots as before |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] `ansible/requirements.yml` pins `konstruktoid.hardening` to an exact version and lists `community.general`.
- [ ] The `host_hardening` role includes only allow-listed areas, and the allow-list is `automatic_updates` alone.
- [ ] The area's Molecule scenario asserts the effect, not only a zero exit, passes the idempotence check, and appears in the scenario matrix.
- [ ] Every host in `patched_hosts` has security-only unattended updates with no automatic reboot.

## Agent handoff

- **Must not change:** the allow-list beyond `automatic_updates`, and the roles whose settings collide with an area in [ADR 0043](../decisions/0043-host-os-hardening-baseline/revision-000.md)'s Context.
- **Relevant files and interfaces:** `ansible/requirements.yml`, `maintenance.yaml`, and the collection's `automatic_updates` role at the pinned version.
- **Required checks:** `pre-commit run --all-files`, and the new Molecule scenario.

## Risks

- The collection is pre-1.0, so a version bump can change an included area's defaults. A bump reruns every included area's scenario.
- `maintenance.yaml`'s package upgrade and a background unattended run may contend for the package manager's lock.
- Stage 1's exit condition is only fully proven by the CI Molecule job, which installs both collections and runs the scenario in a container.

## Open items

- Which areas follow the first, and in what order, is for successor projects; the collisions listed in ADR 0043's Context set the order in which they can be added.
- The operator host, the CD agent, and the coding-agent host include the role from their own projects. This project cannot close while one still lacks it unless a successor project covers it.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or named by a successor project.
- [ ] The linked revision is `accepted`, another project still names it, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
