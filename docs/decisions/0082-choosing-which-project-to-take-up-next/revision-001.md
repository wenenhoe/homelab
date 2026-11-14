---
id: ADR-0082
revision: 1
type: adr
title: Choosing which project to take up next
short: Choosing the next project
solution: "Derive the order from what the docs already record: an Unblocks count and approved decisions listed first; store no priority and keep no view that ranks startable projects"
summary: How the repo shows which project or decision to take up next across initiatives, when status and dependencies are recorded but a preferred order between unrelated projects is not.
topic: documentation-process
status: superseded
superseded_by: 2
supersedes: 0
related: [ADR-0028, ADR-0037]
---

# Unblocks and approved-first, with no ranked view of startable projects

## Problem

More projects can be started than there is time for, and they belong to
unrelated initiatives, so build order and dependencies do not rank them.
What has to be true: the repo shows what stands in the way of each project and
how much waits behind it, and what it shows is kept true by the same changes
that alter the work, not by someone remembering to edit it.

## Decision

Store no priority, rank or urgency on a project or on a decision revision, and
keep no generated view that orders startable projects. The generator derives
what it shows from frontmatter that is already validated, and the schema in
[`doc_frontmatter.py`](../../../tools/doc_scripts/doc_frontmatter.py) does not
change.

- **Unblocks.** Every project row in the generated views carries the number of
  existing projects that wait on it, directly or through a chain of
  `depends_on` entries. A project nothing waits on shows `—`. A dependency on a
  project that no longer exists is ignored, as it is for "waiting on", and a
  dependency cycle counts each project once.
- **Decisions awaiting a project.** A row whose uncovered revision is approved
  sorts ahead of a working one, since an approved revision that no project
  names is the one gap in that table that calls for a project. Within each
  group the order is the lineage number.

## Invariants

- No frontmatter field of a project or a decision revision carries a rank,
  priority or urgency.
- Every figure and ordering in these views is computed from frontmatter alone,
  so a change to a project or to its decision revision that alters the answer
  needs no separate edit.

## Non-goals

- Expressing urgency, risk, deadlines or effort.
- Limiting how many projects are in flight at once.
- Ranking decisions that have no project, beyond listing approved ones first.

## Reconsideration triggers

- The maintainer keeps choosing between startable projects by a rule the docs
  could hold: reconsider a capped `focus` flag, weighed against the public-repo
  constraint above.
- A second maintainer needs to express an order between startable projects.
