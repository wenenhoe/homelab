---
id: PROJ-licence-check
title: Licence Check
type: project
status: not-started
blocked: false
summary: A registry of every pinned dependency's licence, a check when a pin changes, and a weekly check of each upstream's default-branch licence file, as ADR 0090 decides.
decision: ADR-0090/0
allowed_paths:
  - tools/ci/licenses/**
  - tools/tests/ci/licenses/**
  - .github/workflows/check-licenses.yml
  - .github/workflows/pr-checks.yml
  - docs/topics/engineering/ci/licence-check.md
  - docs/topics/engineering/ci/scheduled-jobs.md
  - docs/topics/engineering/ci/pipeline.md
  - docs/topics/README.md
---

# Licence Check

Makes the licence rule of [ADR 0090 (Adopted software licences)](../decisions/0090-licences-of-adopted-software/revision-000.md) a check. A registry names the licence of every pin the repository holds, a job compares it with the upstream's licence file when a pin changes, and a weekly run compares it with the upstream's default branch, so a relicensing shows up before the release that carries it. It is staged because the first stage settles what the check can read, and the checks depend on the answer.

## Scope

The registry, the two checks and their tests, the topic doc, and the schedule and pipeline docs that list them. The registry covers what the repository pins today: images, release binaries, Python dependencies, Tofu providers, pre-commit hooks, Ansible collections and GitHub Actions. It follows the pattern of the checksum and provenance checks' registries, including a test that fails when a pin has no entry, without changing either of them.

Not in this project: replacing software whose licence turns out not to be approved (a finding of Stage 1 that is its own change), a legal reading of any licence, and software an image carries beyond what its pin names.

## Decision

Implements [ADR 0090 (Adopted software licences)](../decisions/0090-licences-of-adopted-software/revision-000.md), still `working`. The project stays `not-started` until that revision is `approved`, and Stage 1 resolves the two assumptions that keep it from being so.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Read the licence file of `itzg/mc-backup`, `docker-compose-linter`, `croniter` and `curl` at their pinned versions, and spike reading `uv.lock` metadata for transitive dependencies | Not started | Each of the four is recorded as approved or as needing an exception or a replacement, and the transitive question is answered, both in the ADR's Assumptions |
| 2 | The registry and the check run when a pin changes | Not started | Every pin has an entry, a test fails when one does not, and the `pr-checks.yml` job fails on an entry whose licence is missing, unrecognised or not OSI-approved |
| 3 | The weekly check and the topic doc | Not started | `check-licenses.yml` compares each entry with its upstream's default-branch licence file on the schedule, reports through the path the other weekly checks use, and the topic doc describes both checks |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] Every pin the repository holds has a registry entry naming its SPDX identifier and the source it was read from.
- [ ] A new pin without an entry fails a test.
- [ ] A change to a pin whose licence is missing, unrecognised or not OSI-approved fails the pull request check.
- [ ] The weekly run fails when an upstream's default-branch licence file no longer matches its entry.
- [ ] The three software exceptions of ADR 0090 are the only ones in the registry, each with its reason.
- [ ] The behavior is described in a new topic doc, `docs/topics/engineering/ci/licence-check.md`, listed in the schedule table, and the ADR is `accepted`.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the ADR's Decision. A licence the check reports as not approved is a finding for the maintainer, not something to resolve by adding an exception.
- **Relevant files and interfaces:** [`tools/ci/checksums/`](../../tools/ci/checksums/registry.py) and [`tools/ci/provenance/`](../../tools/ci/provenance/registry.py) for the registry pattern and their weekly workflows for the schedule pattern.
- **Required checks:** `pre-commit run --all-files`, and `uv run pytest` from `tools/`.

## Risks

- A licence file that is not one of the common texts is read as unrecognised, so an approved project can fail the check until its entry records the text it carries.
- The check needs the upstream's source repository for every pin, and a few pins name a registry image without a source label.
- Reading a licence file from GitHub depends on its availability and rate limits.

## Open items

- Whether the check descends into lock files for transitive dependencies, which Stage 1's spike answers.
- Where the weekly run's failure is reported, which follows whatever the other weekly checks do.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
