---
id: ADR-0082
revision: 1
type: adr
title: Choosing which project to take up next
short: Choosing the next project
solution: "Derive the order from what the docs already record: an Unblocks count and approved decisions listed first; store no priority and keep no view that ranks startable projects"
summary: How the repo shows which project or decision to take up next across initiatives, when status and dependencies are recorded but a preferred order between unrelated projects is not.
topic: documentation-process
status: accepted
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

## Context

[`projects/README.md`](../../projects/README.md) records each project's
lifecycle status, a `blocked` flag, its `depends_on` entries, and the status of
the decision revision it names. The generated views derive "waiting on" from
those, and the README says why: "Neither is a status, so neither needs an edit
when it changes." What they cannot say is which of two startable projects in
different initiatives to take first. `depends_on` cannot either, since the
README reserves it for work that "cannot proceed until that project is done",
not for "preferred order".

A finished project's doc is deleted together with the `depends_on` entries that
name it, so a count over the docs that exist stays right without an edit.

Revision 0 added a generated Next up view that listed the startable projects
in an order. The maintainer does not use it: the project tables already show a
project's status and what blocks it, and the choice between startable projects
is a judgement the view did not make. Keeping it meant a ranking to maintain
and test for no reader.

"Priority" covers three things. Readiness is derived. Leverage, how much waits
behind a project, follows from `depends_on`. Urgency and risk are a judgement
that nothing in the repo records.

[ADR 0028 (Doc metadata)](../0028-doc-metadata-and-governance/revision-000.md)
rejected a metadata field that nothing renders, and declined to stamp an
evaluative label on an accepted decision.

**Constraint from the public repo.** A stored urgency on a security-related
project tells any reader that a gap exists, and git history dates every change
to it. The rule in [`docs/README.md#public-repo`](../../README.md#public-repo)
rules out recording why, so such a label would carry a claim the repo cannot
explain. `priority band` already names the image vulnerability ranking in
[ADR 0071 (Image vulnerability assessment)](../0071-assessing-the-vulnerabilities-of-deployed-container-images/revision-000.md).

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

## Alternatives considered

- **The Next up view of revision 0**, listing startable projects by status and
  then Unblocks. Dropped: it is not used, and the project tables carry the same
  facts.
- **A stored `priority` label on projects.** No check can tell that it is out of
  date. It folds readiness, leverage and urgency into one value, runs into the
  public-repo constraint above, and the name is taken by ADR 0071.
- **The same label on decision revisions.** It describes scheduling, not what
  was decided, and an accepted revision could not take it without a new
  revision.
- **A capped `focus` flag** on the few projects to take up next. Deferred; see
  the reconsideration triggers.
- **An order written by hand in a doc.** No check can compare it with the
  dependencies it has to respect, so it drifts.

## Consequences

- Two derived figures and orderings have to stay correct. Tests and the hook
  that regenerates the views cover that.
- Unblocks counts projects, not stages or effort.
- Choosing between startable projects stays a judgement. Nothing in the docs
  expresses urgency or risk.
- [`project-planning.md`](../../project-planning.md) describes the views,
  [`docs/projects/README.md`](../../projects/README.md) the derived labels, and
  [`doc-checks.md`](../../topics/engineering/ci/doc-checks.md#doc-index-generation)
  the generator.

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

## Validation

`tools/tests/doc_scripts/test_generate_doc_indexes.py` covers the count (direct,
chained, cyclic, and with a missing predecessor) and the approved-first order.
The `generate-doc-indexes` hook regenerates the views on every commit, so a
stale one fails the commit.

## Reconsideration triggers

- The maintainer keeps choosing between startable projects by a rule the docs
  could hold: reconsider a capped `focus` flag, weighed against the public-repo
  constraint above.
- A second maintainer needs to express an order between startable projects.
