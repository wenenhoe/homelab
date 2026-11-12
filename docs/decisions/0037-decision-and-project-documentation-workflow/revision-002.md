---
id: ADR-0037
revision: 2
type: adr
title: "Recording decisions, tracking execution, and keeping docs true"
short: Decision and project workflow
solution: "Several projects may implement one decision; the last one to close accepts it, enforced when a project doc is deleted"
summary: "How why, what-remains, and what-is-true-now are kept apart, extended so one decision can be implemented by more than one project."
topic: documentation-process
status: superseded
superseded_by: 3
supersedes: 1
related: [ADR-0061]
---

# Letting several projects implement one decision

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
  `check-project-scope.py` (renamed: `check_project_scope.py`) does. A PR that deletes a project doc fails
  unless that doc's `decision:` revision is `accepted` afterwards or is
  still named by a project doc in the PR's result. `also_implements:`
  doesn't count as naming, since it gates nothing.
- **The lifecycle table's `done` row** reads "`accepted`, or `approved`
  while another project still names it".

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

## Reconsideration triggers

- A revision is repeatedly found `approved` with no project after its
  last closure, meaning the parallel-close gap is real. Make the
  "awaiting a project" view an error or add a merge-time check.
- Sharing becomes common enough that listing which Decision bullets each
  project covers (an `implements:` list) is worth its upkeep.
