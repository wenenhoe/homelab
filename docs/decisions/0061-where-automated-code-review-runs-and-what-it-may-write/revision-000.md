---
id: ADR-0061
revision: 0
type: adr
title: "Where automated code review runs, and what it may write"
solution: "Both CodeRabbit's PR-diff review and a periodic agent-driven full-repo audit run from homelab-security's own CI, and neither holds a credential that can write to this repo"
summary: "How this repo gets automated code review without any of it becoming visible on this repo's own surfaces, or able to alter it unsupervised."
topic: security-hardening
status: approved
related: [ADR-0020, ADR-0044, ADR-0050, ADR-0051, ADR-0060]
---

# 0061. Where automated code review runs, and what it may write

## Problem

Automated review of this repo's code must never make its findings
visible on any surface this repo itself controls — a PR comment, an
Actions run log — before a human has seen them, and whatever produces
those findings must not be able to alter this repo on its own.

## Context

[ADR 0060](../0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-000.md)
puts findings in a private tracker, but that alone doesn't stop the
*process* of reviewing from leaking through a channel other than its
final report — a GitHub Actions run defined in or triggered from this
repo's own `.github/workflows/` is public the moment it runs, same as a
PR comment.

Two kinds of review are planned. CodeRabbit's CLI reviews each new pull
request's diff — cheap, fast, and (per a sampled review) good at
breadth: it independently caught the same bug in five separate files. A
periodic full-repository audit by a coding agent covers what CodeRabbit
structurally can't: it chunks a review by directory and file count, with
no visibility into `docs/decisions/` — a sampled finding flagged
`vault-bootstrap.hcl` as root-equivalent without knowing
[ADR 0025](../0025-admin-capability-without-a-standing-root-token/revision-000.md)
already reasons through and accepts exactly that property. An agent
reading the whole repo, including its ADRs, doesn't have that blind
spot.

**Threat model.** The adversary is the review process's own output being
steered — a finding, a comment, or a file read during review is
AI-generated or AI-read content that could be crafted to manipulate
whatever reads it next, the same class of risk
[ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md)
already names for the coding-agent host (*"a compromised or misdirected
agent session, for example one steered by content in a dependency or
repository file"*). The asset is this repo's `main` and, through
[ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-a.md),
everything the CD agent deploys from it. The attack path is any
credential reachable by a review process that can write to this repo's
GitHub remote.

## Decision

- Both review jobs are defined and triggered from `homelab-security`'s
  own Actions, never from this repo's.
- `homelab-security` reads this repo by a plain, unauthenticated clone.
  Reading a public repo needs no credential, and none is granted.
- Neither job holds a credential that can write to this repo's GitHub
  remote. All output goes only into `homelab-security`
  ([ADR 0060](../0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-000.md)) —
  never a commit, comment, or check here.
- `homelab-security` triggers a per-PR CodeRabbit review by polling this
  repo's PR list on a schedule, not by a credential-bearing dispatch call
  originating from a workflow in this repo — keeps every credential
  capable of touching the private repo out of the public repo's secrets
  entirely.
- This is a distinct identity from
  [ADR 0051](../0051-coding-agent-execution-isolation/revision-000.md)'s
  coding-agent host. That host is interactive-only and deliberately
  holds no standing credential (`ANTHROPIC_API_KEY` and
  `CLAUDE_CODE_OAUTH_TOKEN` unset; sign-in by login only). The review
  agent here is unattended and does hold a standing, narrowly-scoped
  credential ([ADR 0062](../0062-automation-identity-for-the-agent-based-reviewer/revision-000.md)) —
  a different job with a different trust profile, not a variation on the
  coding-agent host's.

## Alternatives considered

- **`repository_dispatch` from this repo, with a private-repo-scoped PAT
  stored as this repo's secret.** Puts a credential capable of touching
  `homelab-security` inside this repo's own secret store — a new
  surface, for a project not currently accepting external pull requests,
  bought only for lower review latency. Rejected as the default;
  reconsider if latency becomes a real problem.
- **Run the audit agent on the coding-agent host.** Rejected — that host
  is deliberately built to hold no standing credential and require
  interactive login every session ([ADR 0051](../0051-coding-agent-execution-isolation/revision-000.md)).
  Giving it one for this job would undo the property that ADR exists to
  guarantee.

## Consequences

A new PR's review latency is bounded by `homelab-security`'s poll
interval, not instant. The full-repo audit's chunking is decided by the
agent at runtime — reading whatever files and docs a given area actually
needs — rather than fixed upfront by directory and file count, at the
cost of needing its own judgment calls about what belongs together.

## Invariants

No credential held by either review process can write to this repo's
GitHub remote. Nothing about a finding's content is ever written to a
surface this repo's own git history, PR comments, or Actions logs
expose.

## Non-goals

Which credential authenticates the audit agent
([ADR 0062](../0062-automation-identity-for-the-agent-based-reviewer/revision-000.md)).
`homelab-security`'s internal structure ([ADR 0060](../0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-000.md)).

## Reconsideration triggers

This project starts accepting external pull requests — changes the
fork/dispatch trust calculus behind the "no dispatch from this repo"
default. Review latency becomes an operational problem worth trading a
new secret for.
