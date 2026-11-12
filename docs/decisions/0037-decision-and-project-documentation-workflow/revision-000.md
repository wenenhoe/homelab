---
id: ADR-0037
revision: 0
type: adr
title: "Recording decisions, tracking execution, and keeping docs true"
short: Decision and project workflow
solution: "Problem-oriented ADR lineages with gated revisions, projects as execution records, topic docs describing main"
summary: "How why, what-remains, and what-is-true-now are kept apart, and how an implementer knows what is authorized and when to stop."
topic: documentation-process
status: superseded
superseded_by: 1
narrows: ADR-0028
---

# 0037. Recording decisions, tracking execution, and keeping docs true

## Problem

The repo needs three different things written down — why it is built
this way, what remains to be built, and how it behaves now — without
them bleeding into each other, and in a form a human or an agent can act
on: what is authorized, what is done, and when to stop and ask.

## Decision

- **ADRs are lineages.** One directory per problem, one revision per
  solution (the original is revision 000), in the states `working`, `approved`, `accepted`,
  `superseded`, `abandoned`, and `retired`. Titles name the problem.
  Part-replacement is a new lineage that `narrows` the old one. The
  rules are in [`decisions/README.md`](../README.md).
- **Assumptions gate implementation.** An `approved` or `accepted`
  revision has no open assumption. A new one found during
  implementation returns the revision to `working`.
- **Projects are execution records.** They are grouped by
  `super_project`, `track`, and `phase` labels, ordered by `depends_on`,
  and move through `not-started`, `de-risking`, `building`, `done`, with
  `blocked` as a flag. A project's status fixes the state its
  `decision:` revision must be in. The rules are in
  [`projects/README.md`](../../projects/README.md).
- **Topic docs describe `main`** at every commit; git and the PRs hold
  implementation history.
- **Checks enforce it.** `check-doc-drift.py` (renamed: `check_doc_drift.py`) fails on a broken
  invariant; the indexes are generated from frontmatter.
- **Agents** may append an open assumption and set `approved` to
  `working` on an ADR revision, and nothing else. They stop at the stop
  conditions in the projects README.
