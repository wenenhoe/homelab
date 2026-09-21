---
id: PROJ-coding-agent-access-path
title: Coding-Agent Access and Review Path
type: project
status: not-started
blocked: false
summary: Split maintainer client identities and the fetch-review-push workflow, so the coding-agent host never holds or reaches a push credential.
decision: ADR-0055/0
super_project: coding-agent-host
track: workflow
phase: 1-access-path
depends_on:
  - project: PROJ-coding-agent-host
    reason: The forced-command fetch key and the driving key are installed on the host, which must exist first
  - project: PROJ-workstation-management
    reason: The driving identity and its SSH and editor configuration are defined by the workstation role
---

# Coding-Agent Access and Review Path

How the maintainer drives the agent and gets its work into `main`. Staged because a spike must confirm the restricted fetch key works before the workstation's identities are split around it.

## Scope

The low-privilege driving identity on the workstation, the host-side fetch key, the git remote and review workflow, and the checks that the host holds no git credential and the driving identity cannot read infrastructure keys. Not in scope: the host ([`coding-agent-host.md`](coding-agent-host.md)) and firewall rules ([`coding-agent-network.md`](coding-agent-network.md)).

## Decision

Implements [ADR 0055](../decisions/0055-maintainer-client-access-to-the-coding-agent-host/revision-000.md), `working`. It also carries out the workflow in [ADR 0050](../decisions/0050-agent-authored-changes-reaching-production/revision-000.md), which has no project of its own: that revision is set to `accepted` in the PR that completes Stage 3.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike: a forced-command key serves `git fetch` for a repository owned by the agent account | Not started | The assumption in ADR 0055 is resolved |
| 2 | Driving identity (defined in the workstation role) and the host-side keys | Not started | The driving identity connects with its dedicated key only, with agent, X11, and port forwarding off; the fetch key cannot open a shell |
| 3 | Fetch-review-push workflow documented | Not started | The remote setup, review-before-execute rule, and push step are in a topic doc; ADR 0050 is `accepted` |
| 4 | Credential checks | Not started | The host holds no git credential of any kind, and the driving identity cannot read infrastructure keys or the push credential |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] No token, SSH key, or credential-helper entry that can write to GitHub exists on the host, confirmed from outside it.
- [ ] The driving identity cannot read the infrastructure keys or push credential.
- [ ] The privileged account has never opened an interactive session to the host, and its key cannot.
- [ ] The workflow is described in a topic doc.

## Risks

- OS-account separation may prove weaker than needed; the fallback is a separate client VM, or terminal-only access ([ADR 0055](../decisions/0055-maintainer-client-access-to-the-coding-agent-host/revision-000.md)).
- Review discipline is manual.

## Open items

- Whether OS-account separation with a desktop session per identity is enough; the same question sits in [ADR 0056](../decisions/0056-credentials-held-by-the-maintainer-workstation/revision-000.md).

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
