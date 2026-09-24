---
id: PROJ-doc-workflow-shared-decisions
title: "Docs Workflow: Shared Decisions"
type: project
status: building
blocked: false
summary: "Let several projects implement one ADR revision: a sibling-aware done gate, a deletion-time close check, and the lifecycle docs."
decision: ADR-0037/2
allowed_paths:
  - .github/scripts/**
  - tools/tests/doc_scripts/**
  - .github/workflows/pr-checks.yml
  - .config/.pre-commit-config.yaml
  - docs/projects/README.md
  - docs/ci.md
  - docs/decisions/0037-decision-and-project-documentation-workflow/revision-001.md
---

# Docs Workflow: Shared Decisions

Implements the rule in
[ADR 0037 revision 2](../decisions/0037-decision-and-project-documentation-workflow/revision-002.md):
more than one project may name the same revision, and the last one to
close accepts it. It touches the doc tooling, CI, and the lifecycle
docs, and is staged so each script change lands with its own tests before
the docs describe the new behavior.

## Scope

- `doc_graph.py`'s gate for `done` becomes sibling-aware.
- A new close check, beside `check-project-scope.py`, fails a PR that
  deletes a project doc unless its `decision:` revision is then
  `accepted` or still named by another project.
- The check runs as a CI job and a pre-commit hook.
- `docs/projects/README.md`'s lifecycle table, closing checklist, and
  "When a project finishes" describe the rule; `docs/ci.md` describes the
  job.
- Not changed: the gates for the other statuses, what `also_implements:`
  records, and any ADR other than this one's own revision and revision
  1's supersession metadata.

## Decision

[ADR 0037 revision 2](../decisions/0037-decision-and-project-documentation-workflow/revision-002.md).
Rationale lives there.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Make `done`'s gate in `doc_graph.py` sibling-aware, with tests | Done | `done` naming an `approved` revision passes only while another non-`done` project names it; `pytest tools/tests/doc_scripts` and `check-doc-drift.py` pass |
| 2 | The close check script, with tests | Done | Deleting the last project naming an unaccepted revision fails; accepting it, leaving a sibling, or adding a successor passes |
| 3 | Wire the check into `pr-checks.yml` and pre-commit; describe it in `docs/ci.md` | Not started | The job runs on a PR and a hook run locally agrees with it |
| 4 | Update `docs/projects/README.md`; accept ADR 0037/2 and mark revision 1 `superseded` | Not started | `pre-commit run --all-files` passes with revision 2 `accepted` and revision 1 `superseded` |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] A project at `done` may name an `approved` revision only while
      another project not at `done` names it.
- [ ] A PR deleting a project doc fails unless that doc's `decision:`
      revision is `accepted` afterwards or another project still names it.
- [ ] `docs/projects/README.md` states the rule in its lifecycle table,
      closing checklist, and "When a project finishes", including the
      checklist item that every Decision bullet is implemented or named
      by a successor project.
- [ ] ADR 0037 revision 2 is `accepted` and revision 1 is `superseded`.

## Agent handoff

Stop conditions are in [`README.md#stop-conditions`](README.md#stop-conditions);
they apply without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the gates for statuses other than `done`; how
  `also_implements:` is validated; `check-project-scope.py`'s scope rule.
- **Relevant files and interfaces:** `.github/scripts/doc_graph.py`
  (`PROJECT_DECISION_GATE` and the project loop), `check-project-scope.py`
  (how it reads the base ref), `tools/tests/doc_scripts/`, the
  `project-scope` job in `pr-checks.yml`.
- **Required checks:** `pytest tools/tests/doc_scripts`,
  `pre-commit run --all-files`, and `check-project-scope.py`.

## Risks

None open.

## Open items

None.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
