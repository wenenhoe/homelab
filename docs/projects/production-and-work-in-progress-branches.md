---
id: PROJ-production-and-work-in-progress-branches
title: "Production and Work-in-Progress Branches"
type: project
status: building
blocked: false
summary: Three long-lived branches where only main is deployed, a promotion checklist on pull requests into main, and Renovate's branch realigned before each run.
decision: ADR-0076/0
allowed_paths:
  - tools/ci/promotion/**
  - tools/ci/branches/**
  - tools/tests/ci/promotion/**
  - tools/tests/ci/branches/**
  - tools/tests/ci/test_stdlib_only.py
  - .github/workflows/pr-checks.yml
  - .github/workflows/promotion-checklist.yml
  - .github/workflows/renovate.yml
  - .github/workflows/warm-caches.yml
  - .github/renovate.json5
  - docs/topics/engineering/ci/**
  - docs/topics/engineering/branching.md
---

# Production and Work-in-Progress Branches

Carries out [ADR 0076 (Branch separation)](../decisions/0076-keeping-what-production-runs-apart-from-work-in-progress/revision-000.md): `main` stays what the CD agent deploys, while dependency updates and development collect on `maintenance` and `develop`. It is staged so the branches exist only once the checks already run on them.

## Scope

In: running the existing checks on pull requests into `maintenance` and `develop`, pointing Renovate at `maintenance`, the promotion checklist, the realignment step before each Renovate run, and the topic doc for the maintainer's flow.

Not in: the CD agent, which keeps fetching `main` only ([`tools/cd_agent/run_job.py`](../../tools/cd_agent/run_job.py) is not changed), a second environment, automated realignment of `develop`, and publishing images from any branch but `main`. Creating the branches and their rulesets is done by the maintainer in GitHub settings, and the stage that needs them says so.

## Decision

Implements [ADR 0076 (Branch separation)](../decisions/0076-keeping-what-production-runs-apart-from-work-in-progress/revision-000.md), revision 0.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Close the open assumptions with throwaway spikes on a scratch repository, covering rulesets and force pushes, the Renovate token's push rights, Renovate after a base-branch rewrite and after a merge, cache restore across branches and a compose pin that precedes its image | Done | Each assumption's entry is deleted from the revision, its fact folded into Context or the Decision changed, with nothing from the spikes committed |
| 2 | The revision is approved | Done | The revision is `approved`, with no open assumption |
| 3 | Every check that runs on a pull request into `main` also runs on one into `maintenance` or `develop`, and caches warm on the branches the spikes showed need it | Not started | A test over the workflow triggers asserts it, and a pull request into each new branch runs the full set |
| 4 | The promotion checklist: a tested path-to-command mapping and a workflow that writes it into the description of a pull request into `main` | Not started | The mapping's unit tests pass against diffs of the paths it names, and a pull request from `maintenance` shows the list between its markers with the maintainer's own text intact |
| 5 | The Renovate workflow realigns `maintenance` before it runs, and Renovate targets it | Not started | The realignment's tests pass on temporary repositories (fast-forward, merge, conflict left unchanged and failing), and a Renovate run opens its pull requests into `maintenance` |
| 6 | The maintainer's flow is documented, and the CI topic docs describe the new triggers | Not started | A topic doc covers promotion, realignment of `develop` and a fix straight to `main`, and `pipeline.md` and `gates.md` match the workflows |

Stage status is `Not started`, `In progress`, or `Done`.

Stage 1 is the only stage that runs while the revision is `working`. Stages 3 to 6 start after stage 2, and the project then moves to `building`. The maintainer creates `maintenance`, `develop` and their rulesets before stage 3's exit check, and sets the ruleset on `main` before the first promotion.

## Acceptance criteria

- [ ] The CD agent fetches `main` and no other ref, verified by the existing agent tests being unchanged and passing.
- [ ] A force push to `main` is refused and a push to `maintenance` or `develop` without a pull request is accepted for the maintainer's token, verified by attempting each.
- [ ] A pull request into any of the three branches runs the same required checks, verified by a test over the workflow triggers.
- [ ] No workflow publishes an image from a branch other than `main`, verified by a test over the build workflows' triggers.
- [ ] The checklist names the command for each rule's path pattern and never fails a merge, verified by unit tests and one real pull request.
- [ ] Realignment fast-forwards or merges and never rewrites or force-pushes, and a conflicting merge leaves `maintenance` unchanged and fails the run, verified by the realignment's tests.
- [ ] Renovate does not run against a `maintenance` that failed to realign, verified in the workflow.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the revision's Decision except as stage 1 and the stop conditions in [`README.md#stop-conditions`](README.md#stop-conditions) permit; the CD agent and the jobs it runs; any ruleset, which is the maintainer's to set.
- **Relevant files and interfaces:** `BRANCH = "main"` in `tools/cd_agent/run_job.py`; the `main` triggers in `pr-checks.yml`, `warm-caches.yml` and the `build-*-image.yml` workflows; `baseBranchPatterns` in `.github/renovate.json5`. The code lives where [ADR 0064 (CI and doc check code)](../decisions/0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md) puts CI code, stdlib-only.
- **Required checks:** `pre-commit run --all-files`; `uv run pytest tools/tests/ -v`.

## Risks

- A conflict between `main` and `maintenance` holds back that day's Renovate run until the maintainer resolves it.
- A new workflow or trigger has to keep the required-check aggregator `matrix-jobs-gate` accurate on all three branches.
- A dependency update, security ones included, reaches production only when `maintenance` is promoted.

## Open items

- Which commands the checklist rules ask for, beyond `uv sync`, `ansible-galaxy` and the deploy playbooks, is settled against the paths the maintainer has had to run by hand.
- Whether `develop` needs the schedule-gated checks that run only on `main`.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
