---
id: ADR-0082
revision: 2
type: adr
title: Choosing which project to take up next
short: Choosing the next project
solution: "Keep the derived Unblocks count and add a Roadmap view with a row per initiative, in a maintainer-kept order, and a column per derived state; the order ranks initiatives, never a project, and no frontmatter field carries it"
summary: How the repo shows which project or decision to take up next across initiatives, when status and dependencies are recorded but a preferred order between unrelated projects is not.
topic: documentation-process
status: working
supersedes: 1
related: [ADR-0028, ADR-0037]
---

# An initiative roadmap in a kept order, with no rank on a project

## Problem

More projects can be started than there is time for, and they belong to
unrelated initiatives, so build order and dependencies do not rank them.
What has to be true: a reader sees what stands in the way of each project, how
much waits behind it, and which initiative the maintainer wants worked first,
and none of it is kept true by someone remembering to edit it.

## Context

Revision 0 had a Next up view that listed startable projects by status and
Unblocks; revision 1 dropped it as unused and kept no view that ranks startable
projects. The maintainer still chooses between them, by initiative:
which goal to move before which, while other goals keep moving in parallel. A
single ranked list of projects does not say that, and revision 1 listed a hand
written order as an alternative because no check can compare it with the
dependencies it has to respect.

An order between initiatives has no dependency to contradict. An initiative's
own projects keep their dependency order, which is derived. The remaining
risk is the one revision 1 named: a stored order is a stored urgency, and git
history dates each change to it. The rule in
[`docs/README.md#public-repo`](../../README.md#public-repo) rules out
recording why, so the order carries no reason.

## Decision

Add a **Roadmap** view as the first section of the generated
[project planning](../../project-planning.md): one row per initiative, in the
order the maintainer keeps, then a last row for projects with no
`super_project`. The columns are the same for every row and derive from what
each project already records:

| Column | A project is in it when |
| :--- | :--- |
| In progress | Its status is `building` or `de-risking` |
| Startable | It is `not-started` and its Blocker is `—` |
| Waiting | It is `not-started` and something stands in the way |

A cell lists the projects in dependency depth, then file name, as the Super
Projects view does, each with its Unblocks count when that is not zero. A
`done` project is not shown.

- **The order** is a numbered list of initiatives in
  [`projects/README.md`](../../projects/README.md), each with one line saying
  what the initiative delivers. It says nothing about why an initiative stands
  where it does. It reads as where to look first, not as a rule that a later
  initiative waits for an earlier one: work in any row that has a startable
  project.
- **A check** fails the generator when a `super_project` value is missing from
  the list, appears twice or has no project, so a new initiative cannot be left
  unplaced and a finished one cannot linger.
- **Nothing is stored on a project or a decision revision.** The list is the
  only place an order exists. It sits outside the generated views, because
  patches leave those out.

## Alternatives considered

- **One ranked list of projects.** Rejected for the reason revision 1 gave: it
  drifts from the dependencies, and it says nothing about parallel work.
- **A stored `priority` or `lane` field on projects.** Still rejected: no check
  can tell it is out of date, and each edit is a dated claim.
- **Initiatives as columns.** Each new initiative would widen the table until
  it no longer reads.
- **Topics as columns or rows.** A decision's `topic` is a subsystem, not a
  goal: the CD agent and the KMS image share one. Most initiatives sit inside
  one topic, so a topic by initiative grid would be mostly empty.
- **A separate roadmap document holding the order.** Patches leave out the
  generated views, so a list inside one would be lost with them. The list has
  to live in a hand-kept file anyway, which leaves the new document a second
  home for one view, and renaming `project-planning.md` would break the links
  that name it.
- **The order in a private repository.** The maintainer chose to keep the
  roadmap public; see the assumption below.

## Assumptions

- **Claim:** A coarse order between initiatives, with no reason attached, does
  not tell a reader that a given security gap exists.
  **Breaks if wrong:** The list has to leave the public repo, and the view
  would need a private input.
  **Checked by:** The maintainer's review of the first list before approval.

## Consequences

- The generator reads one more input and enforces its coverage, so a test
  covers the row order, the last row, the column rules and each failure.
- The order is a judgement the docs now hold. It can be wrong and nothing
  says so; the dated history of the list is the only record of what it was.
- A project's priority inside an initiative is still not expressed.
- [`project-planning.md`](../../project-planning.md) describes the view and
  [`doc-checks.md`](../../topics/engineering/ci/doc-checks.md#doc-index-generation)
  the generator.

## Invariants

- No frontmatter field of a project or a decision revision carries a rank,
  priority or urgency.
- The only stored order is the initiative list, and it holds initiatives, not
  projects.
- Every other figure and ordering in the views is computed from frontmatter.

## Non-goals

- Expressing urgency, risk, deadlines or effort.
- Dates, modes or availability: the roadmap says what comes before what, not
  when.
- Ranking decisions that have no project.

## Validation

`tools/tests/doc_scripts/test_generate_doc_indexes.py` covers the row order,
the last row, the column of each status, the order within a cell and the three
failures of the check.
The `generate-doc-indexes` hook regenerates the views on every commit.

## Reconsideration triggers

- The list changes often enough that its dated history reads as a log of
  urgency.
- A second maintainer needs an order inside an initiative.
