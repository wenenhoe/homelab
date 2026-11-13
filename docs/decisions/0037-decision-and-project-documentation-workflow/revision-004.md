---
id: ADR-0037
revision: 4
type: adr
title: "Recording decisions, tracking execution, and keeping docs true"
short: Decision and project workflow
solution: "Open questions live in explorations until a choice is made, decisions come in two weights, a project starts only on an approved decision, and accepted records are kept small by condensing, merging and demoting"
summary: "How why, what-remains, and what-is-true-now are kept apart, extended with a home for unsettled questions, a lighter record for small decisions, and a way to compact accepted records."
topic: documentation-process
status: superseded
superseded_by: 5
supersedes: 3
related: [ADR-0061, ADR-0080, ADR-0082]
---

# Explorations before decisions, two weights of decision, and compaction

## Decision

Everything in revisions 0 to 3 stands except where this revision says
otherwise.

**Explorations.** An exploration is a question that has no chosen solution.

- One file per question under `docs/explorations/`, named by a slug, with no
  number. Its frontmatter carries `id` (`EXP-<slug>`), `type: exploration`,
  `title` (the question, without naming a solution), `summary`, `topic`
  (the decision topics) and `status: open`. Its body has the question, the
  facts that matter, the options and what each would cost, and optionally a
  leaning.
- It ends in one of three ways: a decision is written (light or full), a
  project is opened for work that needs no decision, or the question is
  dropped. The pull request that does this deletes the exploration, and a
  decision it creates carries the rejected options in its Alternatives.
- References run one way. An exploration may link to decisions, topic docs and
  projects; nothing else links to an exploration, and a check fails a link
  that does.
- A reconsideration trigger of an accepted revision that fires opens an
  exploration. It ends in a new revision of that lineage or is dropped.
- The generated planning view lists open explorations with the date of their
  last commit, and the check warns on one that has not changed for longer than
  a limit set in the check. The public-repository rule applies to it as to any
  doc.
- A `working` revision is a chosen solution with open assumptions. A question
  with no chosen solution is an exploration.

**Two weights of decision.** A revision carries `weight: full` or
`weight: light`, defaulting to `full`.

- A decision is full when it touches a trust boundary, a credential, a path
  that can lose data or block recovery, or would take more than one pull
  request to reverse. Anything smaller is light. A choice that would not
  surprise a reader of the code is not recorded as a decision: it goes in a
  topic doc or in the conventions.
- A light revision has a problem, the context that matters, the decision,
  the reason it beat the alternative, and what would reopen it. It has no
  Invariants, Non-goals or Validation, and a ceiling on its length, which the
  check holds.
- Lineages, states, supersession and the index work the same for both. A light
  record that needs invariants becomes a new full revision.

**Projects follow decisions.**

- A project may be `not-started` only when its decision is `approved`, or when
  it names none. A project that names a `working` revision is `de-risking`,
  limited to spikes and reading code, as the lifecycle table already says.
- A project doc that names only `working` revisions may be deleted
  unfinished. The revision then shows in "Decisions awaiting a project".
- The generated view and the check warn when more projects are `building` or
  `de-risking` than a limit set in the check.
- `super_project` stays; `track` and `phase` are dropped. Order between
  projects is a dependency, or it is not recorded.

**Compacting accepted records.** These apply only to `accepted` and
`superseded` revisions, are made by the maintainer, and are never made by an
agent working a project.

- *Condense.* An accepted revision may be shortened in place if its Problem,
  Decision, Invariants, Non-goals and Reconsideration triggers are unchanged.
  A check compares those sections with the base branch and fails the change
  when they differ, so a condense cannot alter what was decided. Context
  narration, Consequences and Validation may be cut.
- *Merge.* Records that are one problem become one new lineage with a new
  number. It carries every Decision point, Invariant, Non-goal and trigger of
  each source, lists their numbers in `former_ids`, and takes over their
  inbound links and `related:` entries in the same change. The source
  directories are deleted, and the re-check of the NIST mapping that a
  superseded record already requires is done in the same change. The merged
  revision is `accepted` only if every source was accepted and no Decision
  point changed. Any change of decision is an ordinary revision first.
- *Demote.* A record that is an implementation detail moves to a topic doc or
  the conventions first, then is deleted with its inbound links rewritten.
  Its number is listed, with where it went, in a ledger of removed
  numbers kept beside the decisions README, and a new lineage may not take a
  listed number.
- Candidates are found by an advisory script, and a generated report is read
  every quarter. Neither edits anything.

## Invariants

- A question that has no chosen solution is not a decision, and no decision or
  topic doc depends on an exploration.
- An accepted revision's Problem, Decision, Invariants, Non-goals and triggers
  change only by a new revision, or not at all.
- A merge or a demotion loses no Decision point, Invariant, Non-goal or
  trigger without a record of where it went.
- A number is never reused.

## Non-goals

- A priority for explorations or projects. ADR 0082 stands.
- A way for an agent to compact records unattended.
- Exploration of private-side work, which waits for its own decision.

## Reconsideration triggers

- Open explorations pile up faster than they close.
- A merge or condense loses reasoning that a later reader needed.
- Light records keep being revised into full ones.
- External contributors open pull requests, so the doc workflow needs a gate
  that the maintainer-only rules do not.
