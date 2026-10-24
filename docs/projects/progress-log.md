---
id: PROJ-progress-log
title: Progress log
type: project
status: building
blocked: false
summary: Generate the weekly and monthly record of work from main's history and publish it to the progress-log branch from a scheduled workflow.
decision: ADR-0095/0
allowed_paths:
  - tools/progress_log/**
  - tools/tests/progress_log/**
  - .github/workflows/progress-log.yml
  - .github/detect-changes-filters.yml
  - docs/topics/engineering/progress-log.md
  - docs/topics/engineering/ci/scheduled-jobs.md
  - docs/topics/README.md
---

# Progress log

Builds the generator and the scheduled workflow that [ADR 0095](../decisions/0095-recording-what-was-worked-on-each-week-and-month/revision-000.md) decides on. It is staged because the generator is tested on its own before a workflow that holds `contents: write` exists, and the first scheduled run can only be checked on GitHub.

## Scope

The `tools/progress_log/` package and its tests, the `progress-log.yml` workflow, the entries that make a change to either run the unit tests, the workflow's row in the scheduled-jobs table, and a topic doc. Not in scope: creating the `progress-log` branch and its ruleset, which the maintainer has done by hand, and any change to `main`'s rulesets or branch protection.

## Decision

[ADR 0095 (Progress log)](../decisions/0095-recording-what-was-worked-on-each-week-and-month/revision-000.md), revision 0. Rationale and invariants live there.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The generator and its tests | Done | `python -m progress_log` writes the weekly files, monthly files, index and `state.json` from a git repository, and its tests pass, including that resuming gives the same files as a full rebuild |
| 2 | The scheduled workflow | Not started | `progress-log.yml` runs daily and on demand, only its publishing job holds `contents: write`, a test asserts that, and its row is in the scheduled-jobs table |
| 3 | The topic doc | Not started | The topic doc says how to read the log, how notes survive, and how to rebuild it, and is in the topics index |
| 4 | First live run | Not started | The maintainer has dispatched the workflow once, the branch holds the log and `state.json`, and a second run adds only what is new |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] A scheduled run publishes to `progress-log` and to no other ref, and nothing reaches `main`.
- [ ] A rejected push fails the run.
- [ ] A closed week's file is not rewritten by a later run, and its hand-written notes survive.
- [ ] When the recorded commit is not an ancestor of `main`, the run rebuilds every week keeping notes, with a normal commit on top.
- [ ] The generator imports only the standard library, and its tests run in the unit-test job.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the rulesets or branch protection of any branch; `docs/projects/README.md`, `docs/project-planning.md` and `docs/decisions/README.md`, which are generated.
- **Relevant files and interfaces:** `tools/progress_log/`, `.github/workflows/check-image-tags.yml` (the pattern for a scheduled workflow), `tools/tests/ci/test_stdlib_only.py` and `test_layout.py`.
- **Required checks:** `uv run pytest` from `tools/`, ruff, and the doc hooks.

## Risks

- The first scheduled run can't be exercised before merge; stage 4 is the maintainer's dispatch, and the project stays `building` until then.
- The log's grouping is rule-based and can label a change oddly; the notes section under each period is where that is corrected by hand.

## Open items

None.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
