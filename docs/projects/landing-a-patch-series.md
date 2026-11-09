---
id: PROJ-landing-a-patch-series
title: Landing a patch series
type: project
status: building
blocked: false
summary: A maintainer-run tool that lands a series of patches as pull requests into main, one at a time from fresh branches, after replaying the series and running the checks.
decision: ADR-0112/0
allowed_paths:
  - tools/land_series/**
  - .github/detect-changes-filters.yml
  - docs/topics/engineering/ci/change-scoping.md
  - tools/tests/land_series/**
  - docs/topics/engineering/landing-a-series.md
  - docs/topics/README.md
---

# Landing a patch series

Builds the tool [ADR 0112 (Landing a patch series)](../decisions/0112-landing-a-series-of-dependent-changes-on-main/revision-000.md) describes. Staged because the merge flag has to be shown to work before anything is built on it, and the replay is useful before the pull requests are.

## Scope

A `tools/land_series` package, its tests and a topic doc. Not in scope: the rulesets, the workflows and the branch filter, none of which the decision changes.

## Decision

Implements [ADR 0112 (Landing a patch series)](../decisions/0112-landing-a-series-of-dependent-changes-on-main/revision-000.md), `approved`: the merge flag works against the bypass, so the tool can be built.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike: `gh pr merge --admin` against the `main-review` bypass | Done | A pull request is merged into `main` from the command line with the flag, or is refused and the outcome is recorded in the decision; the assumption is resolved and the revision is `approved` |
| 2 | The manifest and the replay | Not started | A file of a manifest and an mbox is parsed, and its layers replay in order on a scratch worktree of `origin/main`, one `git am` per patch with the views reset, and the no-Docker checks run at each state; a layer already in `main` is skipped, and a layer on the stop list halts the run until confirmed |
| 3 | The pull requests | Not started | Each layer is pushed on a branch fresh from `main`, opened, waited on and merged with the admin flag, and an open pull request whose patch changed is replaced; a series of three layers lands in order |
| 4 | The topic doc | Not started | `landing-a-series.md` describes the input, the stops and how to run the tool, has its row in `topics/README.md`, and ADR 0112 is `accepted` |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] A series of at least three layers lands as three pull requests, each with a merge commit and each reverting alone.
- [ ] A layer that changes a path on the stop list does not run until the maintainer confirms.
- [ ] A scope failure that a missing widening layer causes shows before any pull request exists.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the rulesets, the workflows, `.githooks/`.
- **Required checks:** the tool's unit tests, `pre-commit run --all-files`.

## Open items

Whether the tool belongs in `tools/` as a package or as a script beside the doc tools.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
