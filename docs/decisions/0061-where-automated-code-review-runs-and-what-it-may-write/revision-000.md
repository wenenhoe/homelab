---
id: ADR-0061
revision: 0
type: adr
title: "Where automated code review runs, and what it may write"
solution: "A periodic agent-driven full-repo audit runs from homelab-security's own CI and holds no credential that can write to this repo; CodeRabbit's PR-diff review stays a local run by the maintainer"
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

Two kinds of review exist. CodeRabbit's CLI reviews a branch's diff —
cheap, fast, and (per a sampled review) good at breadth: it independently
caught the same bug in five separate files. The maintainer runs it by
hand, which keeps its output on their terminal (see
[Alternatives considered](#alternatives-considered)). A periodic
full-repository audit by a coding agent, run from `homelab-security`'s
CI, covers what CodeRabbit structurally can't: it chunks a review by directory and file count, with
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
[ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-c.md),
everything the CD agent deploys from it. The attack path is any
credential reachable by a review process that can write to this repo's
GitHub remote.

## Decision

- The audit job is defined and triggered from `homelab-security`'s own
  Actions, never from this repo's.
- `homelab-security` reads this repo by a plain, unauthenticated clone.
  Reading a public repo needs no credential, and none is granted.
- The audit job holds no credential that can write to this repo's GitHub
  remote. All output goes only into `homelab-security`
  ([ADR 0060](../0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-000.md)) —
  never a commit, comment, or check here.
- A local CodeRabbit review runs on the maintainer's machine and prints
  to its terminal. Nothing from it is committed here or posted to a pull
  request.
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

- **Run CodeRabbit's per-PR review from `homelab-security`'s CI, polling
  this repo's pull request list.** Unattended use needs a headless
  Agentic API key, which the plan in use does not issue; the CLI's
  interactive login does not work in a scheduled run. Rejected; the
  maintainer runs the CLI by hand before a push instead.
- **Run the audit agent on the coding-agent host.** Rejected — that host
  is deliberately built to hold no standing credential and require
  interactive login every session ([ADR 0051](../0051-coding-agent-execution-isolation/revision-000.md)).
  Giving it one for this job would undo the property that ADR exists to
  guarantee.

## Consequences

A pull request's diff is reviewed by CodeRabbit only when the
maintainer runs it. The full-repo audit's chunking is decided by the
agent at runtime — reading whatever files and docs a given area actually
needs — rather than fixed upfront by directory and file count, at the
cost of needing its own judgment calls about what belongs together.

## Invariants

No credential held by the audit process can write to this repo's
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
default. Headless CodeRabbit access becomes available at no cost, which
would let a per-PR review run from `homelab-security`'s CI again.
