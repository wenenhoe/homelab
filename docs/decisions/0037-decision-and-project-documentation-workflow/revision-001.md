---
id: ADR-0037
revision: 1
type: adr
title: "Recording decisions, tracking execution, and keeping docs true"
solution: "also_implements: as a validated, non-gating frontmatter field, plus a generated view of open ADRs no project covers"
summary: "How why, what-remains, and what-is-true-now are kept apart, extended to close a visibility gap the original method left open."
topic: documentation-process
status: accepted
supersedes: 0
related: [ADR-0050, ADR-0055]
---

# Formalizing which ADRs a project covers, and surfacing the ones none does

## Context

An audit of every open (`working`/`approved`) ADR lineage found several
with no project tracking their implementation, invisible in
[`docs/decisions/README.md`](../README.md)'s per-topic index without
reading every row's Status column by hand. Two of the audit's apparent
hits turned out not to be gaps: a project can legitimately have no
`decision:` yet because nothing is `approved`
([`cd-agent.md`](../../projects/cd-agent.md), ADR 0044), and a project
can complete a *different* lineage than the one it's gated on
([`coding-agent-access-path.md`](../../projects/coding-agent-access-path.md),
`decision: ADR-0055/0`, whose Stage 2 also sets
[ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md)
to `accepted`). Distinguishing these by hand each time doesn't scale,
and the interim fix — asking a project to say so in free prose — has
no fixed phrase to check for: an earlier patch cited both situations as
the same pattern, and the correction needed its own revision to
[`docs/projects/README.md`](../../projects/README.md) once the mixup was
found. Prose readable by a person isn't the same thing as a signal a
script can rely on.

## Decision

Add `also_implements:` to a project doc's frontmatter: a list of
revision references in the same format as `decision:` (`ADR-0050/0`),
naming a lineage this project's stages complete as a side effect,
distinct from the one it's gated on. `check-doc-drift.py` validates
each entry resolves to a real lineage revision, the same check
`decision:` already gets — but `also_implements:` never enters
`PROJECT_DECISION_GATE`; it records a fact, and gates nothing.

Add a generated table to a new topic doc,
[`docs/project-planning.md`](../../project-planning.md): every ADR
lineage with an open revision that appears in no project's `decision:`
or `also_implements:`. Move the existing `## By initiative` table there
too — a planning/build-order view, not a rule, and it doesn't belong in
[`docs/projects/README.md`](../../projects/README.md) any more than the
new table would.

`generate-doc-indexes.py` grows a fourth target file; the `## Index`
table an agent may need to reference for `check-project-scope.py`'s
reverse-link check stays exactly where it is, in
`docs/projects/README.md`.

## Alternatives considered

- **Keep the prose-only convention, just word it more carefully.**
  Still not something a script can check; the exact failure this
  revision exists to fix. Rejected.
- **A single `implements: []` list, replacing `decision:` entirely.**
  Every existing project doc's own prose already uses "Implements
  [ADR NNNN]" to mean the one *gating* decision specifically. Collating
  a non-gating completion into the same list means either every entry
  gates identically (wrong: `coding-agent-access-path.md` doesn't need
  ADR 0050 at any particular status to build) or only the first entry
  gates (the same two concepts, just distinguished by list position
  instead of a field name — harder to get right in review). Rejected.
- **Put the "needs a project" table in `docs/decisions/README.md`
  instead of a new doc.** It's a filtered, cross-cutting view of rows
  already shown per-topic there, and answering "what's a project
  waiting on" reads as a `projects/`-side question as much as a
  `decisions/`-side one. A dedicated doc avoids stretching either
  file's stated scope. Rejected.

## Consequences

- Four scripts change: `doc_frontmatter.py` (schema), `doc_graph.py`
  (resolves `also_implements:` the way it already resolves `decision:`),
  `generate-doc-indexes.py` (the new table, and `By initiative`'s new
  home), and `check-doc-drift.py`'s index check now covers a fourth
  generated file.
- The new table can't detect a project that references an ADR only in
  free prose, with neither field set — `cd-agent.md`/ADR 0044's
  still-undecided case will keep appearing there until 0044 is
  approved and `decision:` is set. That's a correct, if imprecise,
  result: no *formal* link exists yet. Reading a listed ADR's own
  `related:` lineages, or the project index by hand, remains a real
  step this table doesn't remove.

## Invariants

- `also_implements:` never participates in `PROJECT_DECISION_GATE`;
  only `decision:` gates a project's lifecycle status.
- `docs/projects/README.md`'s `## Index` continues to link every
  project doc by filename, independent of where `By initiative` lives.

## Non-goals

- Modeling a project gated on more than one ADR at once. No current
  instance needs it; see Reconsideration triggers.
- Fully automating the judgment an ADR is genuinely tracked somewhere
  in prose without a formal field — the new table narrows where to
  look, not the need to look.

## Validation

`pre-commit run --all-files` regenerates
[`docs/project-planning.md`](../../project-planning.md), so it can't go
stale silently. `check-doc-drift.py` fails a project doc whose
`also_implements:` entry doesn't resolve to a real lineage revision,
same as it already does for `decision:`.

## Reconsideration triggers

- A project genuinely needs to gate on more than one ADR simultaneously
  — revisit whether `decision:` itself should become a list then,
  rather than stretching `also_implements:` to do double duty.

## Revision notes

Revision 1 adds `also_implements:` and the generated "needs a project"
view; revision 0's ADR-lineage/project/topic-doc split, revision
states, and project lifecycle are unchanged.
