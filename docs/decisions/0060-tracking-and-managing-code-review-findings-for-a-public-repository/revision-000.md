---
id: ADR-0060
revision: 0
type: adr
title: "Tracking and managing code-review findings for a public repository"
solution: "A private tracker repo (homelab-security), issues-based, not a mirror of the public repo's code"
summary: "Where automated code-review findings live, given the repo they describe is public."
topic: security-hardening
status: approved
related: [ADR-0061]
---

# 0060. Tracking and managing code-review findings for a public repository

## Problem

Findings from automated code review of this repo (a severity, a file, a
description of what's wrong) need somewhere to live that isn't this
repo. [`docs/README.md`'s public-repo rule](../../README.md#public-repo)
already forbids recording a live vulnerability, incident, or exposure
window anywhere that reaches this repo's git history — a review finding
is exactly that shape of content.

## Context

A manual review of a produced CodeRabbit report confirmed this isn't
hypothetical: the findings were real and actionable, and exactly what
[ADR 0061](../0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md)
keeps off this repo's own PR comments. Their severity, file, and
description stay out of this repository.

That reasoning extends past PR comments: GitHub Actions run logs on a
public repository are public by default too, so any review computation
triggered from or defined in this repo's own `.github/workflows/` leaks
the same way, regardless of whether the output ever becomes a PR
comment.

## Decision

A private GitHub repository, `homelab-security`, tracks findings as
Issues — one per open finding, each recording the finding's severity,
file, description, and this repo's commit SHA at review time. It is a
tracker, not a mirror: no copy of this repo's code lives there, and
nothing about its own existence needs to stay secret.

## Alternatives considered

- **Private-main repo with periodic sync to this public one.** A
  filtering or squash pipeline that must never leak, running forever, on
  top of — not instead of — the single-repo discipline that already
  works. Doubles the CI surface for one operator. Solves a
  findings-tracking problem with a version-control-architecture-sized
  change. Rejected.
- **GitHub repository security advisories on this repo directly.** A
  real, native fit for anything that reaches genuine vulnerability
  severity — a temporary private fork to build the fix, CI explicitly
  excluded from it. Kept as a complementary path for that tier, not the
  primary mechanism for the routine flow of findings.
- **No private venue; leave the PR-review App disabled and track
  nothing systematically.** Leaves real findings (see Context)
  undiscovered rather than merely undisclosed. Rejected.

## Consequences

A second repository to maintain — issue labels, a finding template — but
no sync tooling and no second copy of this repo's code to keep
consistent with the first.

## Invariants

No finding's severity, file, or description is committed, commented, or
logged anywhere reachable from this repo's own git history, PR comments,
or Actions run logs.

## Non-goals

Where the review computation itself runs, and what credential drives it
([ADR 0061](../0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md)).
`homelab-security`'s internal label scheme and issue template (a project
concern, not an architectural one).

## Reconsideration triggers

`homelab-security` needs to hold real code, not just tracking data — at
that point, re-evaluate a mirror on its actual, demonstrated merits
rather than pre-emptively.
