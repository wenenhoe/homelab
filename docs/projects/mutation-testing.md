---
id: PROJ-mutation-testing
title: "Mutation Testing"
type: project
status: de-risking
blocked: false
summary: "Decide where a mutmut survey of the credential tooling runs and what it writes; the mutation-comparison script stays out of this repo."
---

# Mutation Testing

Whether mutation testing finds weak tests that review and the suite do not.
A throwaway spike answered it: it does, on the modules that handle
credentials. What is left is where the survey runs and what it writes. It
runs from `homelab-security`, not here, because its output is a list of the
behaviours no test guards, and that list does not belong in a public
repository's history, logs or artifacts. The script that compares old and
new tests against mutants of the code under test is not adopted into this
repo; it stays a private tool for the rare change that rewrites tests
without changing the code under test.

## Scope

A scheduled `mutmut` survey of the Python under `tools/`, run from
`homelab-security` the way [ADR 0071](../decisions/0071-assessing-the-vulnerabilities-of-deployed-container-images/revision-000.md)
runs its image scan, with its results kept there. The ADR that decides it,
and the workflow that implements it. Not in scope: changing tests or the
code under test because a mutant survived, which is an ordinary change of
its own; hosting the comparison script in this repo.

## Decision

None yet. [ADR 0069](../decisions/0069-how-python-unit-tests-are-written-and-run/revision-000.md) and [ADR 0070](../decisions/0070-what-a-unit-tests-doubles-are-bound-to/revision-000.md) leave mutation testing out and say a spike answers whether it adds signal before any decision. Stage 2 writes the ADR.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | `mutmut` spike | Done | `mutmut` has run on at least two pure-logic modules whose tests were reviewed in the quality passes, and its result is known in aggregate: mutants run, killed and surviving, the run's time, and what running it here needs. The surviving mutants themselves stay private. |
| 2 | Decide where the survey runs | Not started | An ADR revision states where `mutmut` runs, which modules it covers, what it writes and where, how the run that executes this repo's tests is kept from holding a write credential, and that the comparison script is not a repo tool. It records the spike's result as aggregates only. |
| 3 | Build the survey | Not started | The survey runs on a schedule in `homelab-security`, its first run's output has been triaged by the maintainer, and the ADR is `accepted`. |

## Acceptance criteria

- [ ] The ADR records the spike's result as aggregates only, never a surviving mutant or the test that missed it.
- [ ] The survey runs on a schedule in `homelab-security` and writes only there; nothing from a run reaches this repo's history, logs or artifacts.
- [ ] This repo carries no `mutmut` configuration, import-path workaround or mutants directory.

## Risks

- The survey executes this repo's code and tests in the private repo's CI. The run must hold no write credential, as [ADR 0071](../decisions/0071-assessing-the-vulnerabilities-of-deployed-container-images/revision-000.md) does for the job that runs code taken from this repo.
- `mutmut` keys a mutant by file path, and this repo imports through `pythonpath` roots, so it needs a flat copy of the packages to run. That wrapper lives with the survey, not here.
- The comparison script is a private tool, and no repo rule requires it. A change that edits what a test asserts is checked by review and the suite alone unless its author runs it. A future project that rewrites tests without changing the code under test names the comparison in its required checks, as the unit-test quality passes did.

## Open items

- Whether survey results use the tracker's finding schema or separate records with their own validator, as ADR 0071's do, and the filter that keeps a run's output small enough to triage. Settle it in stage 2.
- Whether running `mutmut` once with the old tests and once with the new, and diffing which mutants each killed, can stand in for the comparison script on a test-only change. Check it by replaying one past test-only change through both tools before relying on it.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or named by a successor project.
- [ ] The linked revision is `accepted`, another project still names it, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
