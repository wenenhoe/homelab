---
id: PROJ-project-start-gate
title: "Project start gate and sizing"
type: project
status: building
blocked: false
summary: "Make a project start only through a gate of an approved decision, a confirmed plan and a complete scope, keep assumptions in the decision, size projects to close on their own, and review the projects that exist against those rules, as ADR 0037 revision 5 decides."
decision: ADR-0037/5
allowed_paths:
  - AGENTS.md
  - docs/README.md
  - docs/decisions/README.md
  - docs/decisions/TEMPLATE*.md
  - docs/projects/*.md
  - docs/topics/engineering/ci/doc-checks.md
  - docs/topics/engineering/ci/pipeline.md
  - tools/doc_scripts/**
  - tools/tests/doc_scripts/**
---

# Project start gate and sizing

Puts [ADR 0037 revision 5 (Decision and project workflow)](../decisions/0037-decision-and-project-documentation-workflow/revision-005.md)
into practice. It is staged because each rule needs a check, and each check is
its own pull request. The rules that apply to every project doc come after the
edits that bring the existing docs into line, so no check fails the repository
as it stands.

## Scope

- The `plan` field, the `de-risking` rule that no stage has started, and the
  removal of assumption, spike and decision-writing stages from every project.
- The start gate: a decision that is `approved`, a confirmed plan, and an
  `allowed_paths` that is set and complete, with `sweep_terms` and the
  exemptions for the files the workflow edits itself.
- The size warnings and the sizing guidance in the projects README.
- A review of every project against the sizing rules, with the merges, splits
  and fixes it finds, each as its own pull request.

Not in scope: stage-level dependencies, a priority for projects, and compacting
decisions.

## Decision

[ADR 0037 revision 5 (Decision and project workflow)](../decisions/0037-decision-and-project-documentation-workflow/revision-005.md),
`approved`. The cut of a superseded revision it records is already in place.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Bring the project docs into line: drop the assumption, spike, decision-writing, acceptance, docs-only and operational-run stages, move a decision-less project that writes its own decision back to an exploration, and give the projects that need one a dependency | Done | No project doc has a stage whose work is to resolve an assumption, to spike, to change a decision's state, to accept, to change docs alone or to run an operation, and each project on a `working` revision is `not-started` or `de-risking` with every stage `Not started` |
| 2 | The shape rules as checks and in the template | Done | `plan` is validated and set `draft` on every project on a `working` decision, which must be a draft; `de-risking` fails when a stage has started; a stage that resolves an assumption, spikes, changes a decision's state, accepts, changes docs alone or runs an operation fails in any project; the template and projects README say so; each has a test and a control that fails without it |
| 3 | The start gate | Done | A change that sets a project `building` fails unless the decision is `approved`, the plan is not a draft and the stage table or a `Plan-Confirmed:` trailer shows it was read, and `allowed_paths` is set |
| 4 | Scope completeness | Done | The gate runs the helper's named-file pass and each `sweep_terms` term and fails on an entry the scope lacks; the topics index, the files naming a deleted project doc and the NIST page for a superseded revision need no entry, so the helper's closing-pull-request pass is gone; a scope narrows only at close |
| 5 | Size warnings and guidance | Done | A check warns on a one-row project that no other project alone depends on, more than six stages, a second stage added after building starts, chained projects naming one revision that no outside reason separates, and a stage that waits on another project in prose; the projects README states the sizing principle and what a stage is |
| 6 | Review the existing projects | Done | Every project and its decision has been read against the sizing rules, and each merge, split or fix that came of it is merged or recorded; each project already `building` carries a scope derived with the helper |

Stage status is `Not started`, `In progress`, or `Done`.

## Review outcomes

Every project was read against the sizing rules (ADR 0037 revision 5).

- Merged: `compose-restart-on-changed-mount` into `bind-mounted-config-files`, as its first stage.
- Kept, with the reason in the project's Open items: `backup-agent-compose-app` and `beszel-agent-docker-api-rules` (one stage each), `coding-agent-egress` after `coding-agent-network`, and `vm-401-retirement` after `workstation-management`.
- Given a scope with the helper: `cd-agent`, `cd-agent-approles`, `cd-agent-job-ssh-keys`, `monitoring-host-isolation` and `opnsense-config`, the projects that were already building.
- Left as they are: `cd-agent` and `cd-agent-approles` name different decisions, so no chain warning fires, though `cd-agent`'s second stage waits on the AppRoles' delivery, which its Open items record. `cd-agent-job-ssh-keys` builds while ADR 0075, which it also implements, is `working`; its third stage starts once that is `approved`.

## Acceptance criteria

- [ ] A project that names a `working` decision and has a stage `In progress` or `Done` fails the check.
- [ ] A change that sets a project `building` without a confirmed plan or an `allowed_paths` fails the check.
- [ ] A scope that lacks a file the helper names for it fails the gate.
- [ ] A one-row project and a project of seven stages each draw a warning and no failure.
- [ ] `pre-commit run --all-files` passes with the new checks on the repository as it stands.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the body of any `accepted` revision, and any project's `status` other than this one's.
- **Required checks:** `pre-commit run --all-files`, and `uv run pytest` from `tools/`.

## Risks

- Stage 1 and the review in stage 6 edit many project docs, and a doc withdrawn or merged loses its stage plan until it is written again.
- A warning that fires on most projects is ignored, so the limits are set from the projects as they stand.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
