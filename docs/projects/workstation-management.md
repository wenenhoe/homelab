---
id: PROJ-workstation-management
title: Maintainer Workstation Management
type: project
status: de-risking
blocked: false
summary: "Bring VM 401 under Ansible management: inventory group, role, per-user remote sessions, and a tested account and SSH configuration."
decision: ADR-0057/0
super_project: maintainer-workstation
track: management
phase: 1-management
---

# Maintainer Workstation Management

Makes VM 401's configuration reproducible from the repo, ahead of splitting what it holds ([`workstation-capability-reduction.md`](workstation-capability-reduction.md)). Staged because two assumptions, per-user remote sessions and self-convergence, need a spike before a role is built on them.

## Scope

An inventory group and play for the workstation, a `workstation` role (accounts, SSH client configuration, remote-login service, editor and tooling), the role's Molecule scenario, and updating [`vm-provisioning.md`](../vm-provisioning.md)'s out-of-scope statement. Not in scope: the OS install, GPU passthrough, other desktops, and what each identity tier holds ([`workstation-capability-reduction.md`](workstation-capability-reduction.md)).

## Decision

Implements [ADR 0057](../decisions/0057-managing-the-maintainer-workstation-from-the-repo/revision-000.md), `working`, so this project is `de-risking` until its two assumptions are resolved.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike: two simultaneous per-user remote sessions over TLS on Ubuntu 26.04, and self-convergence | Not started | Both assumptions in ADR 0057 are resolved and the revision can be `approved` |
| 2 | Inventory group and `workstation` role: accounts, SSH client configuration, remote-login service, editor and tooling | Not started | The play converges idempotently against the workstation from the operator tier |
| 3 | Molecule scenario for what a container can cover | Not started | The scenario passes in CI and appears in the scenario matrix |
| 4 | Topic doc and the `vm-provisioning.md` scope update | Not started | `workstation.md` describes the behavior and `vm-provisioning.md` no longer calls VM 401 wholly out of scope |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] The play rebuilds the workstation's configuration from a fresh OS install without manual steps beyond the install and the first login.
- [ ] Two identities hold separate remote desktop sessions at the same time.
- [ ] The workstation is in none of `managed_hosts`, `app_hosts`, or `patched_hosts`, and no other host has a management path into it.
- [ ] The resulting behavior is described in `docs/workstation.md`.

## Agent handoff

- **Allowed to change:** not scoped yet; `allowed_paths` is added, in its own change, before an agent implements a stage.
- **Must not change:** other hosts' inventory entries and the `all.vars` SSH key.
- **Relevant files and interfaces:** `ansible/inventory/inventory.yaml` (the `controller` group and the `network_infra` pattern), `docs/network-infra.md`.
- **Required checks:** `pre-commit run --all-files`; the role's Molecule scenario.

## Risks

- The desktop and remote-session settings cannot be tested in a container, so they rest on the spike and manual verification.
- Converging the machine that runs the play can interrupt the operator's session.

## Open items

- How Claude Desktop is packaged on Ubuntu 26.04, which decides whether the role can install and pin it.
- Which client the maintainer uses for the remote sessions.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
