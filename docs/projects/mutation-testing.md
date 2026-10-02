---
id: PROJ-mutation-testing
title: "Mutation Testing"
type: project
status: not-started
blocked: false
summary: "Spike whether mutmut adds signal on the pure-logic modules, and decide whether the mutation-comparison script becomes a repo tool."
---

# Mutation Testing

Answers two questions the unit-test quality passes left open, and the first
gates the second: whether mutation testing finds weak tests that review and
the suite do not, and whether the script that compares old and new tests
against mutants of the code under test earns a place in the repo. Staged
because the spike is throwaway and the tool, if it is kept, needs its own
decision first.

## Scope

A throwaway `mutmut` run on the pure-logic modules under `tools/`, a
decision on the comparison script, and, only if that decision keeps it, its
adoption as a tool with a home, a doc and a test. Not in scope: changing
tests or the code under test because a mutant survived; each of those is a
change of its own.

## Decision

None yet. [ADR 0069](../decisions/0069-how-python-unit-tests-are-written-and-run/revision-000.md) and [ADR 0070](../decisions/0070-what-a-unit-tests-doubles-are-bound-to/revision-000.md) leave mutation testing out and say a spike answers whether it adds signal before any decision. Stage 2 writes the ADR if the answer is to keep either tool.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | `mutmut` spike | Not started | `mutmut` has run on at least two pure-logic modules whose tests were reviewed in the quality passes, and the result states what it caught that the existing mutation-comparison script and review did not, with the run's cost in time. |
| 2 | Decide what is kept | Not started | An ADR revision states whether `mutmut`, the comparison script, both or neither is a standing tool, when a change must run it, and where it lives. |
| 3 | Adopt | Not started | Each tool the ADR keeps is in the repo with a doc and a test, and the ADR is `accepted`. Skipped, with this project closed, if the answer is neither. |

## Acceptance criteria

- [ ] Stage 1's result is recorded in the ADR revision of stage 2, not left in a chat or a private copy.
- [ ] Every tool the ADR keeps is in the repo, documented in a topic doc, and covered by a test under ADR 0064.
- [ ] Any rule that makes a test-editing change run a tool is written in the Python unit tests section of [`conventions.md`](../topics/engineering/conventions.md).

## Risks

- Until stage 2 is decided, the mutation comparison is a script kept outside this repo, and no repo rule requires it. A change that edits what a test asserts is checked by review and the suite alone unless its author runs it.
- The comparison script is tied to the `tools/` and `ansible/` test layout through a path pattern in its harness; moving it into the repo means deciding whether to generalise that or keep it local.

## Open items

- Whether the comparison script's operators (comparison swaps, boolean flips, dropped returns and raises, string and integer constants) should be extended to call arguments, default arguments and slicing, which it does not mutate today. Settle it in stage 2, after the spike shows what `mutmut` reaches that it does not.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or named by a successor project.
- [ ] The linked revision is `accepted`, another project still names it, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
