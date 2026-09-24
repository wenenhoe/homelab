---
id: ADR-0037
revision: 2
type: adr
title: "Recording decisions, tracking execution, and keeping docs true"
solution: "Several projects may implement one decision; the last one to close accepts it, enforced when a project doc is deleted"
summary: "How why, what-remains, and what-is-true-now are kept apart, extended so one decision can be implemented by more than one project."
topic: documentation-process
status: approved
supersedes: 1
related: [ADR-0061]
---

# Letting several projects implement one decision

## Context

A project's `decision:` names the one revision it implements, and the
lifecycle requires that revision to be `accepted` before the project is
`done` and its doc is deleted. That assumes one project per decision.
[ADR 0061](../0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md)
broke the assumption: one threat model, implemented by three separate
pieces of work, each with its own project. The first to finish cannot
satisfy the closing checklist, because `check-doc-drift.py` rightly
refuses to let a revision be `accepted` while a project that still needs
it `approved` (`not-started` or `building`) names it.

The tooling already enforces the half that matters most: nothing is
`accepted` while work on it remains. What is missing is a rule for a
project that closes while siblings remain, and a guard for the one that
closes last. Since a finished project's doc is deleted, that guard cannot
read a `status: done` off the tree; it has to see the deletion.

## Decision

Any number of projects may name the same revision in `decision:`. No new
field is needed.

- **A project that is not the last** to name a revision closes without
  touching it. The revision stays `approved`, and the project's closing
  checklist item for the decision is satisfied by another project still
  naming it.
- **The last project** to name a revision must, in the PR that deletes
  its doc, either set the revision to `accepted` or leave another project
  naming it. Accepting asserts that the whole Decision is implemented. If
  part of it is not, the closing PR adds a `not-started` successor
  project for the remainder, which also makes the closing project not the
  last.
- **Enforcement.** A check reads the base the way
  `check-project-scope.py` does. A PR that deletes a project doc fails
  unless that doc's `decision:` revision is `accepted` afterwards or is
  still named by a project doc in the PR's result. `also_implements:`
  doesn't count as naming, since it gates nothing.
- **The lifecycle table's `done` row** reads "`accepted`, or `approved`
  while another project still names it".

## Alternatives considered

- **One project per ADR, splitting ADRs to fit.** Ties an ADR's
  granularity to how the work happens to be divided. An ADR records one
  decision and its rationale; a threat model implemented in three places
  is still one decision. Rejected.
- **Partial acceptance per project** (a status such as
  `partially-accepted`). Dilutes `accepted`, which means implemented and
  on `main`. Rejected.
- **Split the revision when a project closes early.** Writes an ADR
  revision to resolve a scheduling situation. Still the right tool when
  the leftover work really is a different decision (`narrows:` exists for
  that), but not the default. Rejected as the general rule.
- **A checklist item with no check.** The checklist is exactly what
  failed to surface this case. Rejected.

## Consequences

- `doc_graph.py`'s gate becomes sibling-aware for `done`. A new check,
  a sibling of `check-project-scope.py`, runs as its own CI job and
  pre-commit hook, with tests beside the existing ones in
  `tools/tests/doc_scripts/`.
- [`docs/projects/README.md`](../../projects/README.md)'s lifecycle
  table, closing checklist, and "When a project finishes" change, and
  [`docs/ci.md`](../../ci.md) describes the new job.
- A revision can sit `approved` after part of its work has merged.
  `approved` still means only that no open assumptions remain and
  implementation may proceed.
- Two closing PRs that each see the other's project still present would
  leave the revision `approved` with no project. The generated
  "Decisions awaiting a project" view lists it, so the gap is visible but
  not blocked.
- Accepting too early is costly, since an `accepted` revision is
  immutable and a correction is a new revision. The closing checklist
  gains an item: every bullet of the Decision section is implemented or
  named by a successor project.

## Invariants

- `accepted` still means implemented and on `main`; no revision is
  `accepted` while a project naming it in `decision:` is unfinished.
- Deleting a project doc never leaves its `decision:` revision `approved`
  and named by no project.

## Non-goals

- A project gated on more than one ADR at once, as in revision 1.
- Detecting that a Decision bullet has no home. That stays a judgment at
  acceptance, backed by the checklist item.
- Changing what `also_implements:` records.

## Validation

The new check fails a PR that deletes the last project naming an
unaccepted revision, and passes one that accepts it, leaves a sibling in
place, or adds a successor. Tests cover each case, and CI runs it on
every PR.

## Reconsideration triggers

- A revision is repeatedly found `approved` with no project after its
  last closure, meaning the parallel-close gap is real. Make the
  "awaiting a project" view an error or add a merge-time check.
- Sharing becomes common enough that listing which Decision bullets each
  project covers (an `implements:` list) is worth its upkeep.

## Revision notes

Revision 2 lets several projects share one `decision:` and defines who
accepts it and how that is checked. Revision 1's `also_implements:` and
generated view, and revision 0's split of ADR lineages, projects, and
topic docs, are unchanged.
