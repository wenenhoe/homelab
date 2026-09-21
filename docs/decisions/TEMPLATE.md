---
id: ADR-NNNN                 # the lineage: one per problem, identical in every revision
revision: 0                  # the generation: 0 is the original solution; matches revision-NNN.md
# candidate: a               # only when competing solutions share this generation (revision-NNN-a.md)
type: adr
title: "The problem, stated without naming a solution"   # identical in every revision
solution: "This revision's answer, in one line"
summary: "One line on what the problem covers; feeds the generated index"
topic: secrets-store         # one of TOPICS in .github/scripts/doc_frontmatter.py
status: working              # working | approved | accepted | superseded | abandoned | retired
# supersedes: 0              # a later generation: the revision it replaces (a label: 0, or 0-b)
# superseded_by: 1           # required once status: superseded
# narrows: ADR-NNNN          # this lineage replaced part of another lineage's scope
# related: [ADR-NNNN]
# former_ids: [ADR-NNNN]     # numbers retired into this lineage
---

# NNNN. Problem title

## Problem

What has to be true, independent of any solution. If the problem itself
changes, that is a different lineage, not a new revision.

## Context

Constraints, requirements, and facts a reader needs — no narration of
how they were found. If the decision follows from a threat model
(adversary, asset, attack path), give it its own bold-labeled paragraph.

## Decision

The solution, stated plainly. This is the design implementation follows.

## Alternatives considered

Viable options and the decisive reason each lost.

## Assumptions

Open entries only: conditions that must hold for this decision to be
valid. Delete this heading once none remain — a resolved entry becomes a
fact in Context or changes the Decision. A revision can't be `approved`
while any entry is here.

- **Claim:** …
  **Breaks if wrong:** …
  **Checked by:** a spike, reading code, or a named event.

## Consequences

What this costs or leaves unresolved, including accepted risk. Link the
topic doc(s) that describe the resulting behavior — this record stays
short as they grow.

## Invariants

Properties that stay true regardless of how this is implemented.

## Non-goals

What this revision deliberately doesn't solve.

## Validation

What keeps the invariants true after acceptance — a test, a CI check, an
operational signal. Omit if nothing does.

## Reconsideration triggers

Evidence that should prompt a new revision, not a schedule. Omit if none.

## Revision notes

Revision 001 and later only: what changed from the previous revision and
why, as facts. Not an implementation diary.
