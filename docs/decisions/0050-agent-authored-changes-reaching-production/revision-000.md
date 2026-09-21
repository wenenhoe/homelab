---
id: ADR-0050
revision: 0
type: adr
title: Agent-authored changes reaching production
solution: The coding-agent host holds no push credential; the maintainer fetches from it and pushes from the workstation
summary: How changes written by an untrusted coding agent reach main without any credential in the agent's environment being able to alter what the CD agent deploys.
topic: deployment-platform
status: working
related: [ADR-0044, ADR-0020]
---

# 0050. Agent-authored changes reaching production

## Problem

Changes written by an untrusted coding agent reach `main` without any credential reachable from the agent's environment being able to alter what the CD agent deploys.

## Context

[ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-a.md) reduces the deploy trust boundary to who can push to `main`: the CD agent acts on new commits there and holds OpenBao AppRoles and SSH access to the managed hosts. Network and credential separation around the coding-agent host is therefore only as strong as the path its commits take to `main`.

The repository is public, so cloning needs no credential. Only writing does.

**Threat model.** The adversary is a compromised or misdirected agent session, for example one steered by content in a dependency or repository file. The asset is `main`, and through it every host the CD agent reaches. The attack path is any credential on the agent's host that can write to the GitHub remote: whatever runs as the agent account can use it.

## Decision

The coding-agent host holds no credential that can write to the repository's GitHub remote.

The maintainer's workstation adds the host's repository as an additional git remote over SSH, fetches, reviews the diff, and pushes to origin. Push credentials exist only on the workstation.

Fetched content is read as a diff before it is checked out anywhere that executes it (git hooks, pre-commit, Ansible, Molecule, editor tasks).

## Alternatives considered

- **Scoped token or deploy key on the host.** Anything running as the agent can use it, and its limits depend on repository-side settings the host cannot check. Rejected.
- **A separate GitHub machine account working from a fork.** Lets the agent open pull requests unattended, at the cost of a second GitHub identity and a credential in the untrusted plane. A later revision if unattended pull requests become wanted.
- **A credential-issuing proxy on the trusted side.** More machinery than one reviewer needs.

## Consequences

- Work not yet fetched is lost when the host is rebuilt ([ADR 0054](../0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md)).
- The agent cannot open pull requests or trigger GitHub-side workflows.
- Review is a manual step on every change, which is also the point.

## Invariants

- No credential on the coding-agent host can write to the GitHub remote.
- Nothing fetched from the host executes on the workstation before its diff is read.

## Non-goals

- Verifying commit provenance in the CD agent. That concerns the trust of GitHub itself and belongs with [ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-a.md).
- How the workstation connects to the host ([ADR 0055](../0055-maintainer-client-access-to-the-coding-agent-host/revision-000.md)).

## Validation

A check run from outside the host confirms it holds no git credential of any kind: no token, no SSH key, no credential-helper entry. The acceptance criteria of the access-path project carry it.
