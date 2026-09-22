---
id: ADR-0037
revision: 0
type: adr
title: "Recording decisions, tracking execution, and keeping docs true"
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

## Context

- **Findability.** The 36 numbered ADRs are titled after their
  solutions ("Caddy, not nginx-proxy-manager") and indexed in prose, so
  the record of one problem can only be found by already knowing its
  answer. About 22 of the 36 have no relationship to any other ADR.
- **Revision shape.** One ADR was replaced whole (0013 by 0027). Three
  were replaced in part (0015 by 0016, 0019 by 0034, 0031 by 0032), each
  because the earlier record bundled two problems. At least four of the
  15 drafts revise or extend a numbered ADR, and two are competing
  solutions to one problem. The flat model has no place for a successor
  in flight or for competing solutions.
- **Gates.** The rule that no production work starts while an
  assumption is open existed only for `decided` drafts, and only as a
  check on frontmatter status. Projects carried stage-level `De-risking`
  and `Building` statuses derived from drafts, `Blocked` as a status, and
  no dependency model.
- **Agentic implementation** needs the difference between "authorized to
  build" and "built" to be explicit, plus stop conditions that a check
  can see.
- **Industry practice.** Confirmed: the ADR lifecycle of proposed,
  accepted, deprecated, and superseded, with a reversal recorded as a new
  ADR rather than an edit (Nygard's proposal, adr-tools, AWS Prescriptive
  Guidance); a Validation section in MADR 4; the RAID distinction between
  a risk (potential), an issue (current), and a dependency; and
  spec-driven pipelines that run specify, plan, tasks, implement, then
  converge, with clarify and cross-artifact analysis steps (GitHub Spec
  Kit). Original to this repo, with no external precedent found: a
  lineage of successive solutions under one problem; the split between
  `approved` (authorized) and `accepted` (built); returning an approved
  revision to `working` on a new assumption; the project-status to
  revision-state gate; and the agent write limits.
- **Terminology.** Common ADR usage treats "accepted" as binding and
  immutable. Here `accepted` keeps that meaning; `approved` is the added
  state before it.

This narrows ADR 0028: its frontmatter status vocabulary, the drafts
workflow, and the index generation are replaced by the model below. Its
frontmatter adoption and its NIST alignment decision stand.

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
- **Checks enforce it.** `check-doc-drift.py` fails on a broken
  invariant; the indexes are generated from frontmatter.
- **Agents** may append an open assumption and set `approved` to
  `working` on an ADR revision, and nothing else. They stop at the stop
  conditions in the projects README.

## Alternatives considered

- **One ADR per decision, superseded by a new number** — the standard
  model. It has no home for a successor in flight, competing solutions,
  or a partial replacement, and problems are grouped only by prose.
- **Overwrite ADRs in place; rely on git history.** The reasoning at
  decision time and the reason for the change end up in commit messages,
  and there is no revision boundary to hold an agent's edits to.
- **Split bundled ADRs after the fact.** Accepted history isn't
  rewritten. The sizing check prevents new bundling and `narrows`
  handles the residue.
- **Topic subdirectories.** A path that encodes topic breaks links when a
  lineage is reclassified; `topic:` in frontmatter plus a generated
  index doesn't.
- **A hand-written manifest per lineage.** It duplicates revision state
  and drifts; the generated index replaces it.
- **A full external methodology** (sprints, estimation, confidence
  scores). Nothing here needs it.

## Consequences

- Every flat ADR is re-filed once, by script, changing only frontmatter
  and link targets. Numbers stay as identities; 0027 is retired into
  0013, as revision 001 of "secret storage" (0013 itself is its original).
- A new ADR costs a directory and frontmatter. The checks and generators
  become the enforcement, so their tests carry real weight.
- Path-scope enforcement bounds a change that touches a project doc to that
  project's `allowed_paths`, at path level
  ([`docs/projects/README.md#scope`](../../projects/README.md#scope)). The
  handoff's forbidden files, the content of an edit inside an allowed
  file, and a change that never touches its project doc stay advisory.
- Topic docs describing the workflow: [`docs/README.md`](../../README.md),
  [`decisions/README.md`](../README.md),
  [`projects/README.md`](../../projects/README.md).

## Invariants

- An `accepted` revision's reasoning is never rewritten.
- A project is `building` only on an `approved` revision.
- Topic docs describe `main`.
- No security incident, live vulnerability, or exposure window is
  recorded in this repo's docs ([`docs/README.md#public-repo`](../../README.md#public-repo)).

## Non-goals

- Sprints, estimates, story points, or confidence scores.
- Automating the decision itself. An agent never edits the Decision,
  Alternatives, or Consequences of an `approved` or `accepted` revision.

## Validation

`.github/scripts/check-doc-drift.py` enforces the invariants above and is
described in [`ci.md`](../../ci.md#docs-drift-check); its rules are unit
tested under `tools/tests/doc_scripts/`.

## Reconsideration triggers

- Lineages beyond a single revision stay rare after re-filing, so the
  machinery costs more than it returns.
- A partial replacement happens even though the sizing check was applied.
- `approved` versus `accepted` is misread by a human or an agent in
  practice.
- An agent-authored change reaches `main` outside its stated scope.
