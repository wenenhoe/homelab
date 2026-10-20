---
id: ADR-0037
revision: 3
type: adr
title: "Recording decisions, tracking execution, and keeping docs true"
short: Decision and project workflow
solution: "A project doc may be deleted when each revision it names, in decision: or also_implements:, is accepted or still named by a remaining project"
summary: "How why, what-remains, and what-is-true-now are kept apart, extended so a project that implements a second decision on the side can be merged without losing track of that decision."
topic: documentation-process
status: accepted
supersedes: 2
related: [ADR-0061]
---

# Letting a project carry a second decision to its close

## Context

Revision 2 lets several projects share one `decision:` and has the last to
close accept it, enforced when a project doc is deleted. That check reads
`decision:` only. `also_implements:` is a validated field that gates nothing
and, since revision 1, lets the generated "Decisions awaiting a project"
view tell that an open decision is covered.

Merging two projects whose decisions differ and are not yet `accepted` is
therefore impossible. Whichever decision the surviving project does not
carry in `decision:` is left unaccepted and named by no project, so the
check refuses the deletion, even though the survivor can say plainly in
`also_implements:` that it still carries that decision. The refusal is not
wrong about the gap it guards: a decision left `approved` or `working` with
no project is the state revision 2 exists to prevent. It is only blind to a
project that records the decision in the field made for that.

The same blindness runs the other way. A project that lists a decision in
`also_implements:` can be deleted with that decision unaccepted, since only
`decision:` is read at the close. Nothing makes its last carrier accept it.

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

## Alternatives considered

- **Count `also_implements:` as naming only for the doc being merged away.**
  Lets a merge pass but leaves the reverse gap: a project can still be
  deleted with an `also_implements:` revision unaccepted and unnamed.
  Rejected, because the carrier is then trusted at the merge and not at the
  close.
- **Let a project be gated on more than one decision.** Revision 1 did
  this and revision 2 dropped it, since `approved` and `working` gates on
  two revisions conflict. Rejected again.
- **Leave the check and keep the projects apart.** Costs an extra project
  doc and a stage-level dependency stated in prose for every pair of
  related decisions. Acceptable for a pair, but it makes the one real
  merge, two stages of one initiative that share a host, impossible.
  Rejected as the rule.
- **Patch the check for one merge.** Leaves the repo's own rule broken on
  `main`. Rejected.

## Consequences

- A project that lists a revision in `also_implements:` and closes must
  accept it or leave another project naming it. A project that closed
  that way before this revision is not re-judged; the rule reads only the
  docs a PR deletes.
- A merged project is longer-lived than either half: it cannot close
  until both decisions are `accepted`.
- [`docs/projects/README.md`](../../projects/README.md) and
  [`doc-checks.md`](../../topics/engineering/ci/doc-checks.md) describe the
  rule, and `doc_close.py` implements it, with tests beside the existing
  ones in `tools/tests/doc_scripts/`.

## Invariants

- `accepted` still means implemented and on `main`; no revision is
  `accepted` while a project naming it in `decision:` is unfinished.
- Deleting a project doc never leaves a revision it names, in `decision:`
  or `also_implements:`, unaccepted and named by no remaining project.

## Non-goals

- A project gated on more than one ADR at once.
- Detecting that a Decision bullet has no home. That stays a judgment at
  acceptance, backed by the closing checklist.

## Revision notes

Revision 3 widens what "names" means at the close, in both directions.
Revision 2's sharing of `decision:` and who accepts it, revision 1's
`also_implements:` field and generated view, and revision 0's split of
ADR lineages, projects and topic docs are unchanged.
