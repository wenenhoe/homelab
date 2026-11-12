---
id: ADR-0082
revision: 0
type: adr
title: Choosing which project to take up next
short: Choosing the next project
solution: "Derive the order from what the docs already record: an Unblocks count, a generated Next up view, and approved decisions listed first; store no priority"
summary: How the repo shows which project or decision to take up next across initiatives, when status and dependencies are recorded but a preferred order between unrelated projects is not.
topic: documentation-process
status: superseded
superseded_by: 1
related: [ADR-0028, ADR-0037]
---

# 0082. Choosing which project to take up next

## Problem

More projects can be started than there is time for, and they belong to
unrelated initiatives, so build order and dependencies do not rank them.
What has to be true: the repo shows which one to take up next, and what it
shows is kept true by the same changes that alter the work, not by
someone remembering to edit it.

## Decision

Store no priority, rank or urgency on a project or on a decision
revision. The generator derives the order from frontmatter that is
already validated, and the schema in
[`doc_frontmatter.py`](../../../tools/doc_scripts/doc_frontmatter.py)
does not change.

- **Unblocks.** Every project row in the generated views carries the
  number of existing projects that wait on it, directly or through a
  chain of `depends_on` entries. A project nothing waits on shows `—`. A
  dependency on a project that no longer exists is ignored, as it is for
  "waiting on", and a dependency cycle counts each project once.
- **Next up.** A generated view lists the projects that can be worked on
  now: not done, not blocked, waiting on no existing project, and, when
  not started, ready (its decision revision is approved, or it has none).
  Building projects come first so that started work finishes before new
  work opens, then de-risking, then ready ones not yet started. Within
  each, the higher Unblocks count comes first, then the file name. The
  view orders what can be started; it does not rank importance.
- **Decisions awaiting a project.** A row whose uncovered revision is
  approved sorts ahead of a working one, since an approved revision that
  no project names is the one gap in that table that calls for a project.
  Within each group the order is the lineage number, as before.

## Invariants

- No frontmatter field of a project or a decision revision carries a rank,
  priority or urgency.
- Every figure and ordering in these views is computed from frontmatter
  alone, so a change to a project or to its decision revision that alters
  the answer needs no separate edit.
- Next up never lists a project that is done, blocked, waiting on an
  existing project, or not started with a decision revision that is not
  approved.
- In Next up, no building project is listed after a de-risking one, and no
  de-risking project after a ready one.

## Non-goals

- Expressing urgency, risk, deadlines or effort.
- Limiting how many projects are in flight at once.
- Ranking decisions that have no project, beyond listing approved ones
  first.

## Reconsideration triggers

- The derived order repeatedly differs from what is actually started next:
  reconsider a capped `focus` flag, weighed against the public-repo
  constraint above.
- A second maintainer needs to express an order between startable
  projects.
