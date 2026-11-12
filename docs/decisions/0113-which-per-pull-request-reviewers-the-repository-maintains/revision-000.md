---
id: ADR-0113
revision: 0
type: adr
title: Which per-pull-request reviewers the repository maintains
short: Maintained PR reviewers
solution: The requested review is the only per-pull-request review, and the CodeRabbit CLI run with its image, pins, checks and licence exception is removed
summary: Whether the repository keeps the tooling for a per-pull-request reviewer once another reviewer serves the same need.
topic: repository-tooling
status: approved
weight: light
related: [ADR-0061, ADR-0063, ADR-0090]
relies_on:
  - adr: ADR-0061
    reason: "It retires the local run only because the review the maintainer requests from the private checkout takes its place; without that review this record has no reason to stand."
---

# 0113. Which per-pull-request reviewers the repository maintains

## Problem

Each reviewer the repository keeps brings tooling to maintain: an image that
is built, pinned and rebuilt, entries in the checks that watch pins, rules
that bump versions, and a licence exception. A reviewer that another has made
redundant is cost with no purpose, so whether it stays has to be decided.

## Context

[ADR 0061 revision 1 (Automated code review)](../0061-where-automated-code-review-runs-and-what-it-may-write/revision-001.md)
adds a review of a pull request that the maintainer requests from the private
checkout, and leaves open whether the local CodeRabbit run stays. That run was
the only per-pull-request review before it, and the maintainer has chosen the
requested review in its place.

The CodeRabbit CLI is closed source, so it is one of the named licence
exceptions in [ADR 0090 (Adopted software licences)](../0090-licences-of-adopted-software/revision-000.md).
Its image, which [ADR 0063 (Review image build)](../0063-what-the-code-review-image-is-built-from-and-how-it-stays-current/revision-000.md)
decides, is rebuilt weekly, and each version bump needs a hash copied by hand.
The requested review runs from the private repository's CI and needs none of
this.

## Decision

The requested review is the only per-pull-request review. The CodeRabbit run
is retired: its wrapper script, image, workflow, Renovate rules, checksum,
digest and provenance entries, tests and topic doc are removed, and so is its
licence exception. ADR 0063 has no replacement and is retired.

## Alternatives considered

- **Keep the local run beside the requested review.** Rejected: it keeps a
  weekly image build, a version and hash bumped by hand, a closed-source
  exception and entries in three checks, for a run that prints only to a
  terminal and that the requested review now serves.
- **Keep the files and stop bumping them.** Rejected: the pins stay in the
  checks and Renovate keeps proposing bumps, so the cost continues without the
  upkeep that would justify it.

## Reconsideration triggers

The requested review stops being available, which ADR 0061's own triggers
name. Headless CodeRabbit access becomes available at no cost and a second
reviewer is wanted again; that would be a new decision, not a restoration.
