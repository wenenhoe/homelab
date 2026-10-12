---
id: ADR-0060
revision: 0
type: adr
title: "Tracking and managing code-review findings for a public repository"
short: Review findings tracker
solution: "A private tracker repo (homelab-security) holding one structured file per finding, not a mirror of the public repo's code"
summary: "Where automated code-review findings live, given the repo they describe is public."
topic: security-hardening
status: superseded
superseded_by: 1
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

## Decision

A private GitHub repository, `homelab-security`, tracks findings as
files — one structured file per finding, named by a stable identifier,
each recording the finding's severity, file, description, triage status,
and this repo's commit SHA at review time. It is a tracker, not a
mirror: no copy of this repo's code lives there, and nothing about its
own existence needs to stay secret.

## Consequences

A second repository to maintain — a finding schema and template — but
no sync tooling and no second copy of this repo's code to keep
consistent with the first. Deduplication is a file-exists check on the
finding's identifier, and triage is an edit to the file's status. Each
producer run commits its new findings on a branch, validates them, opens
a pull request, and merges it at once: the pull request is what notifies
the maintainer, and merging keeps `main` current for the next run's
deduplication. A new finding is a new file, so writers never conflict on
content.
