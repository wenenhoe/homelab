---
id: ADR-0082
revision: 0
type: adr
title: Choosing which project to take up next
short: Choosing the next project
solution: "Derive the order from what the docs already record: an Unblocks count, a generated Next up view, and approved decisions listed first; store no priority"
summary: How the repo shows which project or decision to take up next across initiatives, when status and dependencies are recorded but a preferred order between unrelated projects is not.
topic: documentation-process
status: accepted
related: [ADR-0028, ADR-0037]
---

# 0082. Choosing which project to take up next

## Problem

More projects can be started than there is time for, and they belong to
unrelated initiatives, so build order and dependencies do not rank them.
What has to be true: the repo shows which one to take up next, and what it
shows is kept true by the same changes that alter the work, not by
someone remembering to edit it.

## Context

[`projects/README.md`](../../projects/README.md) records each project's
lifecycle status, a `blocked` flag, its `depends_on` entries, and the
status of the decision revision it names. The generated views already
derive "waiting on" and "ready" from those, and the README says why:
"Neither is a status, so neither needs an edit when it changes." What the
views do not say is which of two startable projects in different
initiatives to take first. `depends_on` cannot say it either, since the
README reserves it for work that "cannot proceed until that project is
done", not for "preferred order". The same gap exists among decisions
that have no project yet, where the generated table lists them in number
order.

Most projects wait on another one, so only a few can be started at a
time. A finished project's doc is deleted together with the `depends_on`
entries that name it, so a count over the docs that exist stays right
without an edit, the property "waiting on" already has.

"Priority" covers three different things. Readiness is already derived.
Leverage, how much waits behind a project, follows from `depends_on`.
Urgency and risk are a judgement that nothing in the repo records.

[ADR 0028 (Doc metadata)](../0028-doc-metadata-and-governance/revision-000.md)
rejected a metadata field that nothing renders, and declined to stamp an
evaluative label on an accepted decision, whose reasoning does not change
after acceptance. [ADR 0037 revision 1 (Decision and project workflow)](../0037-decision-and-project-documentation-workflow/revision-001.md)
introduced the generated view of decisions awaiting a project.

**Constraint from the public repo.** A stored urgency on a
security-related project tells any reader that a gap exists, and git
history dates every change to it. The rule in
[`docs/README.md#public-repo`](../../README.md#public-repo) rules out
recording why, so such a label would carry a claim the repo cannot
explain. `priority band` already names the image vulnerability ranking in
[ADR 0071 (Image vulnerability assessment)](../0071-assessing-the-vulnerabilities-of-deployed-container-images/revision-000.md),
so the word would also mean two things.

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

## Alternatives considered

- **A stored `priority` label on projects**, with levels such as high,
  medium and low. No check can tell that it is out of date, unlike the
  derived labels. It folds readiness, leverage and urgency into one
  value, with only a few startable projects at a time three levels would
  collapse into one, it runs into the public-repo constraint above, and
  the name is already taken by ADR 0071.
- **The same label on decision revisions.** It describes scheduling, not
  what was decided, and an accepted revision could not take it without a
  new revision. Once a project exists the value would live in two places.
- **A capped `focus` flag** on the few projects to take up next. Deferred.
  It supplies the one thing derivation cannot, a choice between startable
  projects of equal standing, but it is a stored claim again; see the
  reconsideration triggers.
- **An order written by hand in a doc.** No check can compare it with the
  dependencies it has to respect, so it drifts without anyone noticing.

## Consequences

- Three more derived figures and orderings have to stay correct. Tests
  and the hook that regenerates the views cover that.
- Unblocks counts projects, not stages or effort: it says how much waits
  behind a project, not how large or how urgent that project is.
- A not-started project whose decision is still being worked out is not in
  Next up, because it is not ready. Its decision has to settle first.
- Choosing between startable projects of equal standing stays a
  judgement. Nothing in the docs expresses urgency or risk.
- [`project-planning.md`](../../project-planning.md) describes the views,
  [`docs/projects/README.md`](../../projects/README.md) the derived
  labels, and
  [`doc-checks.md`](../../topics/engineering/ci/doc-checks.md#doc-index-generation)
  the generator.

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

## Validation

`tools/tests/doc_scripts/test_generate_doc_indexes.py` covers the count
(direct, chained, cyclic, and with a missing predecessor), who is in Next
up and in what order, and the approved-first order. The
`generate-doc-indexes` hook regenerates the views on every commit, so a
stale one fails the commit.

## Reconsideration triggers

- The derived order repeatedly differs from what is actually started next:
  reconsider a capped `focus` flag, weighed against the public-repo
  constraint above.
- A second maintainer needs to express an order between startable
  projects.
