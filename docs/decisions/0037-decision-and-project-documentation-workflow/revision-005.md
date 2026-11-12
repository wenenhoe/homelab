---
id: ADR-0037
revision: 5
type: adr
title: "Recording decisions, tracking execution, and keeping docs true"
short: Decision and project workflow
solution: "A project builds only after an approved decision and a confirmed plan, its scope is fixed when building starts, a project is sized to close on its own, and a superseded record keeps only what it decided"
summary: "How a project is started, scoped and sized, how a draft plan differs from a confirmed one, and what a superseded decision keeps."
topic: documentation-process
status: approved
supersedes: 4
related: [ADR-0061, ADR-0080, ADR-0082]
---

# Starting a project, fixing its scope, sizing it, and cutting superseded records

## Context

Revision 4 lets a project exist on a `working` decision as `de-risking`, limited to spikes and reading code. Four things followed.

**De-risking became a stage.** Projects waiting on a `working` revision open with a stage that resolves its assumptions or spikes them, and the template tells an author to name such a stage `Spike` and finish it before approval. The two checks that look for it read only the first word of a stage's title and only the docs a change adds, so the stage passes under another name and every project already waiting is left alone. The assumptions are then tracked twice, in the decision and in the project, and some stage exit conditions are only a change to a decision's state.

**A plan written early goes stale unseen.** A project drawn up while its decision is `working` has stages that the resolved assumptions may change, and nothing makes anyone read the stage table again when building starts.

**Scope is guessed too early and widened late.** `allowed_paths` is optional, is set when stages are still unclear, and is widened one pull request at a time as work finds files the author forgot. The helper that suggests a scope is advisory and no check runs it.

**Project boundaries cut across dependencies.** Projects that name one decision are chained by `depends_on` and cannot be accepted until the last closes. Stages wait on another project's stage in prose, where `depends_on` and the planning view cannot see it. Projects with one stage row, and projects that keep gaining stages after building starts, sit beside projects that are plainly one unit of work.

## Decision

Everything in revisions 0 to 4 stands except where this revision says otherwise.

**A superseded revision keeps what it decided.** The change that sets a revision `superseded` also cuts it to its frozen sections: Problem, Decision, Invariants, Non-goals and Reconsideration triggers, as written, with its frontmatter and title. The successor carries Context, Alternatives and the rest. Whoever sets the successor `accepted` makes the cut, agent or maintainer, and the drift check fails a superseded revision that keeps another section. This is part of superseding and not one of the compacting operations; compacting an `accepted` revision stays the maintainer's.

**A project builds on a settled decision and a confirmed plan.**

- Assumptions live only in the decision. No project has a stage whose work is to resolve an assumption, to spike, or to change a decision's state; those are done under the decision, and what a project shows of them is its `de-risking` status. While a decision is `working`, a project that names it is `not-started` or `de-risking` with every stage `Not started`, and its plan is a draft (`plan: draft`), which is for sizing and the roadmap and is not a commitment.
- A question with no decision is an exploration. A project with no `decision:` has no stage whose exit is writing or approving a decision.
- A project starts `building` only through the start gate: its decision is `approved`, its plan is confirmed, and its `allowed_paths` is set and complete. The plan is confirmed by a change that edits the stage table or carries a `Plan-Confirmed: <path>` trailer, which records that the draft was read against the approved decision and stands.

**Scope is fixed when building starts.**

- Every `building` project has `allowed_paths`; no project is exempt for work an agent will not touch, because all work here is agent work.
- The gate runs the checks that find what the scope is missing: the files the doc names, the files the closing pull request edits, and the files that mention each name in the doc's `sweep_terms` (the products, pins, variables and keys the project removes, renames or reshapes).
- The scope then changes only by widening, as its own earlier pull request, or by narrowing at close. A stage added after building starts is a plan revision: it is allowed while the stage is `Not started`, and its paths are widened first.
- A change that works a project doc needs no entry for the files the workflow itself edits: the topics index, the files that name a project doc the change deletes, and the NIST alignment page when it links a revision the change supersedes.

**A project is sized to close on its own.**

- A project is the smallest unit that can be finished and deleted without a stage of another project having to run first. A stage that waits on another project's work is in the wrong project: it moves, or the waiting stages become a follow-on project that `depends_on` the other. There are no stage-level dependencies.
- A stage is a change that merges together with its docs. Acceptance, a docs-only change, writing a decision and an operational run (a rollout, a drill) are not stages: acceptance is the closing checklist, docs travel with the code they describe, a decision is written under the decision, and an operational run is an acceptance criterion.
- A project declares `depends_on` for every project that must be built before it can be applied or live.
- Projects that name one revision and are chained by `depends_on` are one project unless something outside the work separates them in time, such as hardware, or another project depends on the first alone.
- A project with a single stage row is a stage of a neighbour, a single change that needs no project, or under-staged. It is fine when another project depends on it alone. More than six stages, or a second stage added after building starts, prompts a review for a split. A check warns on both and on prose that makes a stage wait on another project; none of them fails.

## Alternatives considered

- **A questions table in the project.** A second copy of the decision's assumptions. Rejected: assumptions stay in the decision.
- **A project is created only when its decision is approved.** Removes the draft plan, which the roadmap needs for sizing. Rejected.
- **Stage-level dependencies.** Makes the planning view exact at the cost of a second kind of dependency to declare and check. Rejected for splitting projects at the dependency.
- **Keep spike stages and fix the title match.** Leaves the same work tracked in two places. Rejected.
- **A word cap for superseded revisions.** The frozen sections cannot be condensed, so a cap would conflict with them. Rejected for a structural rule.
- **A tool that supersedes and condenses in one step.** Duplicates the drift check and the frozen-section code. Rejected for a fix mode on the check.
- **Let a pull request widen its own scope with a trailer.** Removes the point of reading scope from the base branch. Rejected.

## Consequences

- Projects that wait on a `working` revision lose their spike stages and gain `plan: draft`, and `building` projects gain a scope. Both are one-time edits to existing docs.
- Starting a project costs a plan read and a scope derivation at the gate instead of widenings during the work.
- Chained projects on one revision and one-row projects are reviewed and merged, split or kept one at a time.
- [`docs/projects/README.md`](../../projects/README.md), [`docs/decisions/README.md`](../README.md) and the project template state the rules.

## Invariants

- No project builds on a decision that is not `approved` or on a plan that is a draft.
- A decision's open assumptions are recorded in the decision and nowhere else.
- A superseded revision keeps only its frozen sections.
- A project's scope changes after building starts only by a widening pull request that merges first, or at close.

## Non-goals

- Dependencies between stages of different projects.
- A priority for projects. ADR 0082 stands.
- A check that fails on a project's size. Size is a warning and a review.

## Validation

- The shape rules, the start gate and the size warnings are tests under `tools/tests/doc_scripts/`, each with a control that fails without the rule.
- The drift check holds a superseded revision to its frozen sections.

## Reconsideration triggers

- Widenings continue at the rate they had before the gate.
- Draft plans are confirmed by trailer without a change to the stage table in most starts.
- Follow-on projects made by splitting accumulate with no dependency of their own.

## Revision notes

Revision 5 changes how a project starts, how its scope is set, and how it is sized, and records the cut of a superseded revision. Revision 4's compaction operations and explorations are unchanged.
