---
id: PROJ-coding-agent-host
title: Coding-Agent Host
type: project
status: not-started
blocked: false
summary: The dedicated VM, Ansible role, and inventory group that run Claude Code unprivileged under its built-in sandbox.
decision: ADR-0051/0
super_project: coding-agent-host
track: boundary
phase: 2-host
depends_on:
  - project: PROJ-coding-agent-network
    reason: The host's NIC must land in a VLAN whose default-deny policy already exists, so the agent is never run on an open segment
allowed_paths:
  - ansible/roles/coding_agent/**
  - ansible/playbooks/coding-agent.yaml
  - ansible/inventory/**
  - docs/coding-agent.md
  - docs/ansible.md
  - docs/molecule-testing.md
  - docs/README.md
---

# Coding-Agent Host

Replaces the Claude Chat, VS Code, and lazygit workflow with a dedicated VM where Claude Code works autonomously, isolated from the rest of the lab. Staged because the VM, its role, and the role's tests are separate reviewable changes, and the sandbox and sizing assumptions need a spike first.

## Scope

The VM (VMID 601, in the 6XX range), a `coding_agent` role, an inventory group outside `managed_hosts`, `app_hosts`, and `patched_hosts`, an unprivileged agent account, Claude Code with its built-in sandbox, unattended security updates, and the role's Molecule scenario. Not in scope: the network zone ([`coding-agent-network.md`](coding-agent-network.md)), the Molecule runtime for the repo's own scenarios ([`coding-agent-molecule-runtime.md`](coding-agent-molecule-runtime.md)), client access ([`coding-agent-access-path.md`](coding-agent-access-path.md)), and rebuild automation ([`coding-agent-management.md`](coding-agent-management.md)).

## Decision

Implements [ADR 0051](../decisions/0051-coding-agent-execution-isolation/revision-000.md), `working`. The project stays `not-started` while it waits on the network project, and moves to `de-risking` once Stage 1 begins.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike: built-in sandbox on this Ubuntu release with the repo's tooling, and VM sizing under load | Not started | Both assumptions in ADR 0051 are resolved and the revision can be `approved` |
| 2 | VM shell in VLAN 60, built by hand, no nested virtualization | Not started | The VM boots in the zone and is reachable only by the two permitted SSH flows |
| 3 | `coding_agent` role and inventory group: agent and management accounts, Claude Code, sandbox settings, unattended updates, `sshd` per-account source restrictions | Not started | The role converges idempotently and the host resolves its own SSH key, never the shared one |
| 4 | Molecule scenario for the role | Not started | The scenario passes in CI and appears in the scenario matrix |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] The agent runs as an unprivileged account with the built-in sandbox enabled and cannot become the management account or root.
- [ ] `ANTHROPIC_API_KEY` and `CLAUDE_CODE_OAUTH_TOKEN` are unset on the host; sign-in is by interactive login only.
- [ ] The host holds no OpenBao credential, infrastructure SSH key, or git credential, confirmed by a scan run from outside the host.
- [ ] The host is in none of `managed_hosts`, `app_hosts`, or `patched_hosts`.
- [ ] The resulting behavior is described in `docs/coding-agent.md`.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter.
- **Must not change:** other hosts' inventory entries, the `all.vars` key, any existing role's behavior.
- **Relevant files and interfaces:** `ansible/inventory/inventory.yaml` (`all.vars` key inheritance), `docs/network-infra.md` (the pattern for a host outside `managed_hosts`).
- **Required checks:** `pre-commit run --all-files`; the role's Molecule scenario.

## Risks

- The guest shares the node with every other VM, so a hypervisor escape is outside this project's control ([ADR 0051](../decisions/0051-coding-agent-execution-isolation/revision-000.md)).
- Sizing competes with other planned VMs for the node's remaining headroom.

## Open items

- Hostname and admin-account names, following the repo's `<x>admin` convention.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
