---
id: PROJ-docs-process-overhaul
title: "Docs process overhaul"
type: project
status: not-started
blocked: false
summary: "Add the explorations tier and the light decision weight, make projects follow approved decisions, and give accepted records a way to be condensed, merged and demoted, as ADR 0037 revision 4 decides."
decision: ADR-0037/4
allowed_paths:
  - AGENTS.md
  - docs/README.md
  - docs/explorations/**
  - docs/decisions/README.md
  - docs/decisions/TEMPLATE.md
  - docs/decisions/*.md
  - docs/projects/*.md
  - docs/topics/engineering/ci/doc-checks.md
  - tools/doc_scripts/**
  - tools/tests/doc_scripts/**
  - .pre-commit-config.yaml
---

# Docs process overhaul

Puts [ADR 0037 revision 4 (Decision and project workflow)](../decisions/0037-decision-and-project-documentation-workflow/revision-004.md)
into practice. It is staged because each rule needs a check and each check is
its own pull request, and the rules that change the project lifecycle must not
land before the explorations that replace what they remove.

## Scope

- A `docs/explorations/` tier with a template, a check and a section in the
  generated planning view, and a routing table in `AGENTS.md` and
  `docs/README.md` that says which kind of doc a change belongs in.
- A `weight` field on decision revisions, a light template, and the checks that
  hold a light revision to its shape.
- The project lifecycle changes: `not-started` only on an approved decision,
  withdrawal of a project that names only `working` revisions, a limit on
  active projects, and `track` and `phase` removed.
- The compaction checks and tools: the frozen-section comparison, the list of
  removed numbers, and the advisory candidate script with its quarterly report.

Not in scope: compacting the existing decisions. That is a project of its own,
opened when the tools above exist, because it edits many records and each
cluster is reviewed alone. Private-side work waits for its own decision.

## Decision

[ADR 0037 revision 4 (Decision and project workflow)](../decisions/0037-decision-and-project-documentation-workflow/revision-004.md),
`working`. This project waits until the revision is `approved`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Explorations | Not started | `docs/explorations/` has a README and template, a check enforces the frontmatter and one-way references, the planning view lists open explorations with their age, and `AGENTS.md` and `docs/README.md` route a change to the right kind of doc. |
| 2 | Light decisions | Not started | A revision may carry `weight: light`, a template exists, and the check holds a light revision to its sections and length. |
| 3 | Project rules | Not started | The lifecycle table, the close check, the limit on active projects, the removal of `track` and `phase`, and the trimmed template are in place, each with tests and a control that fails without it. |
| 4 | Compaction tools | Not started | The frozen-section check, the ledger of removed numbers with its check, the merge rules in the decisions README, the candidate script and the quarterly report exist, with tests. |
| 5 | Accept the decision | Not started | The corpus project is open, ADR 0037 revision 4 is `accepted`, and this doc is deleted by its closing checklist. |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] A link to an exploration from a decision, topic doc or project fails the
      check.
- [ ] A change to a frozen section of an accepted revision fails the check; a
      change to Context narration passes.
- [ ] A `not-started` project that names a `working` revision fails the check.
- [ ] A project doc that names only `working` revisions can be deleted.
- [ ] `pre-commit run --all-files` passes with the new checks on the repository
      as it stands.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the body of any `accepted` revision except the
  decisions README's editorial cases, and any project's `status` other than
  this one's.
- **Required checks:** `pre-commit run --all-files`, and `uv run pytest` from
  `tools/`.

## Risks

- Removing `phase` drops an order between projects that is not a dependency.
  Each initiative that uses it is checked first.
- A limit on active projects that is set too low warns on every pull request
  and gets ignored.

## Open items

- The values of the stale-exploration limit, the light-revision length ceiling
  and the active-project limit.
- Which of the projects that wait on a `working` revision are withdrawn and
  which stay as spikes. Decided one at a time, since a withdrawn doc's stage
  plan is lost until its revision is approved again.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
