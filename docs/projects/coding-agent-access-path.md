---
id: PROJ-coding-agent-access-path
title: Coding-Agent Access and Review Path
type: project
status: not-started
blocked: false
summary: Terminal-only access to the coding-agent host and the fetch-review-push workflow, so the host never holds or reaches a push credential.
decision: ADR-0055/0
super_project: coding-agent-host
track: workflow
phase: 1-access-path
depends_on:
  - project: PROJ-coding-agent-host
    reason: The maintainer's key is installed on the host, which must exist first
  - project: PROJ-workstation-management
    reason: The SSH client configuration for the host is defined by the workstation role
---

# Coding-Agent Access and Review Path

How the maintainer drives the agent and gets its work into `main`. Staged because the client configuration lives in the workstation role, and the workflow doc and the credential checks are separate changes.

## Scope

The workstation's SSH client entry for the host, the maintainer's key on the host, the git remote and review workflow, and the checks that the host holds no git credential and the workstation's configuration matches the decision. Not in scope: the host ([`coding-agent-host.md`](coding-agent-host.md)), firewall rules ([`coding-agent-network.md`](coding-agent-network.md)), and the workstation role's other contents ([`workstation-management.md`](workstation-management.md)).

## Decision

Implements [ADR 0055](../decisions/0055-maintainer-client-access-to-the-coding-agent-host/revision-000.md), `approved`. It also carries out the workflow in [ADR 0050](../decisions/0050-agent-authored-changes-reaching-production/revision-000.md), also `approved`, which has no project of its own: that revision is set to `accepted` in the PR that completes Stage 2.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | SSH client entry for the host and the maintainer's key on it | Not started | The entry names one dedicated key and disables agent, X11, and port forwarding; no other host uses that key |
| 2 | Fetch-review-push workflow documented | Not started | The remote setup, review-before-execute rule, and push step are in a topic doc; ADR 0050 is `accepted` |
| 3 | Credential and configuration checks | Not started | The host holds no git credential of any kind, and the workstation's client configuration passes the check in ADR 0055 |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] No token, SSH key, or credential-helper entry that can write to GitHub exists on the host, confirmed from outside it.
- [ ] The workstation's entry for the host disables forwarding, uses the dedicated key, and no remote-editor session runs against the host.
- [ ] The workflow is described in a topic doc.

## Risks

- The terminal, SSH client, and git run in the account holding the push credential; that residual risk is accepted in [ADR 0055](../decisions/0055-maintainer-client-access-to-the-coding-agent-host/revision-000.md).
- Review discipline is manual.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
