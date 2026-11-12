---
id: ADR-0037
revision: 3
type: adr
title: "Recording decisions, tracking execution, and keeping docs true"
short: Decision and project workflow
solution: "A project doc may be deleted when each revision it names, in decision: or also_implements:, is accepted or still named by a remaining project"
summary: "How why, what-remains, and what-is-true-now are kept apart, extended so a project that implements a second decision on the side can be merged without losing track of that decision."
topic: documentation-process
status: superseded
superseded_by: 4
supersedes: 2
related: [ADR-0061]
---

# Letting a project carry a second decision to its close

## Decision

A project doc *names* a revision when the revision is its `decision:` or is
listed in its `also_implements:`.

- **Closing.** A PR that deletes a project doc fails unless every revision
  the doc named on the base (its `decision:` and each `also_implements:`
  entry) is `accepted` afterwards or is named by a project doc that
  remains in the PR's result, in either field.
- **Gating is unchanged.** `also_implements:` still gates no project's
  status, and `check_doc_drift.py` still only confirms each entry
  resolves. A revision that a stage sets `accepted` as a side effect is
  still listed there, as before.
- **A merge.** Two projects with different unaccepted decisions can become
  one: the survivor keeps one in `decision:` and lists the other in
  `also_implements:`, and a stage that carries out the second decision says
  so in prose. The survivor cannot close until the second is `accepted`
  too, and it has to accept it, or leave a successor that names it.
- **Everything else in revision 2 stands:** several projects may share a
  `decision:`, the last to name a revision accepts it, and a closing PR
  that leaves part of a Decision unimplemented adds a `not-started`
  successor.

## Invariants

- `accepted` still means implemented and on `main`; no revision is
  `accepted` while a project naming it in `decision:` is unfinished.
- Deleting a project doc never leaves a revision it names, in `decision:`
  or `also_implements:`, unaccepted and named by no remaining project.

## Non-goals

- A project gated on more than one ADR at once.
- Detecting that a Decision bullet has no home. That stays a judgment at
  acceptance, backed by the closing checklist.
