---
id: PROJ-coderabbit-pr-review-pipeline
title: "CodeRabbit PR Review Pipeline"
type: project
status: not-started
blocked: false
summary: "homelab-security's CI polls this repo for new PRs, runs CodeRabbit against each diff, and writes findings as files."
decision: ADR-0061/0
super_project: security-review-pipeline
depends_on:
  - project: PROJ-security-findings-repo
    reason: "Findings need somewhere to be written before this pipeline can run."
---

# CodeRabbit PR Review Pipeline

The steady-state half of [ADR 0061](../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md):
`homelab-security`'s own CI reviews every new pull request against this
repo, without this repo ever seeing the review run.

## Scope

A scheduled `homelab-security` workflow that: reads this repo's open PR
list by an unauthenticated call to the GitHub API; for anything new or
updated since the last check, pulls
`ghcr.io/wenenhoe/coderabbit-review:latest` and runs a `review` against
that PR's diff, authenticated headlessly; parses the `--agent` output
into finding files in `homelab-security`, per
[`security-findings-repo`](security-findings-repo.md)'s schema, one
file per finding ([ADR 0060](../decisions/0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-000.md)):
a finding whose file already exists is left as it is, whatever its
status, and two distinct findings on one PR stay two files. Each run
commits its new files on a branch, validates them, opens a pull request
in `homelab-security` and merges it at once.

Not in scope: the full-repository audit
([`agent-full-repo-audit`](agent-full-repo-audit.md)); the review tool and
its CI-built image, described in
[`coderabbit-review.md`](../coderabbit-review.md).

## Decision

Implements [ADR 0061](../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md),
`approved`.

## Execution plan

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Poll step: list this repo's open PRs, diff against last-checked state | Not started | A new PR opened on this repo is detected by the next scheduled run |
| 2 | Review step: pull the image, authenticate via `--api-key`, run `review` against the detected diff | Not started | A real PR's diff produces `--agent` JSON output, end to end |
| 3 | Finding-writing step: parse findings into `homelab-security` finding files, deduped by identifier, validated, then opened and merged as a pull request | Not started | A finding (or a clean-review confirmation) appears as a merged pull request adding a file that passes `security-findings-repo`'s validator |
| 4 | Cadence and budget spike: confirm the poll interval and per-run review count stay inside CodeRabbit's 3/hour CLI limit (Free plan) and GitHub Actions' minute allowance, against this repo's real merge cadence (~4.2/day average, bursts to ~19/day) | Not started | A measured, not estimated, per-review wall-clock time; a chosen poll interval and schedule that fits both budgets with headroom |

## Acceptance criteria

- [ ] A real PR opened on this repo results in a finding, or a clean-review confirmation, appearing in `homelab-security` within the chosen poll interval.
- [ ] Nothing about the review's output is ever visible on this repo's own PR, commit, or Actions surfaces.
- [ ] A burst of merges in one day queues into subsequent poll cycles rather than failing outright.

## Agent handoff

- **Allowed to change:** the `homelab-security` repo only — nothing in this repo changes as part of this project.
- **Must not change:** this repo's own workflows or secrets; no credential capable of writing to this repo is introduced anywhere.
- **Relevant files and interfaces:** `tools/coderabbit-review/coderabbit-review.sh` (post-trim), `ghcr.io/wenenhoe/coderabbit-review`, the finding schema from [`security-findings-repo`](security-findings-repo.md).
- **Required checks:** none in this repo's CI, since this project's changes live in `homelab-security`.

## Risks

- Burst merge days (observed up to ~19 merges in a single day) exceed the 3/hour CLI allowance if reviewed the moment they land — accepted; excess queues into later poll cycles rather than being dropped.

## Open items

- What makes two findings "the same" when a PR is re-reviewed after an
  update. The dedup step derives each finding's identifier from that
  identity; [`security-findings-repo`](security-findings-repo.md)'s
  schema treats the identifier as opaque, so settle the derivation here
  against real `--agent` output before stage 3.
- Exact poll interval (stage 4).
- Whether GitHub-hosted runner minutes suffice, or a self-hosted runner is worth the small per-minute platform fee GitHub now charges for self-hosted use on private repos — back-of-envelope math suggests GitHub-hosted is likely sufficient; confirm with the stage-4 spike before deciding either way.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or named by a successor project.
- [ ] The linked revision is `accepted`, another project still names it, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
