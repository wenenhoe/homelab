---
id: PROJ-reliance-declaration
title: "Reliance Declaration"
type: project
status: building
blocked: false
summary: A declared reliance between decisions, checked as a warning that names every approved or accepted revision whose boundary still rests on a working one, as ADR 0080 decides.
decision: ADR-0080/0
allowed_paths:
  - tools/doc_scripts/**
  - tools/tests/doc_scripts/**
  - docs/decisions/**
  - docs/projects/README.md
  - docs/project-planning.md
  - docs/topics/engineering/ci/doc-checks.md
---

# Reliance Declaration

Lets a decision say which other lineage's boundary it rests on, and makes the docs check name every approved or accepted revision whose target is not settled yet, as [ADR 0080 (Reliance on working decisions)](../decisions/0080-approved-decisions-resting-on-unfinished-ones/revision-000.md) decides. Staged because the field, the check, the places it shows and the backfill each land on their own.

## Scope

The `relies_on:` field and its validation, the warning and `--strict`, the "Relies on" note in the decisions index, the "rests on" label in the projects index and planning table, and the first population of the field in the revisions whose prose already cites a `working` lineage for an invariant.

Not in this project: clearing the warnings, which is approving each target or revising the reliant decision, and each is its own work; switching CI to `--strict`, which ADR 0080 makes a reconsideration trigger of its own; gating a project on a reliance; and changing what `related:` means.

## Decision

Implements [ADR 0080 (Reliance on working decisions)](../decisions/0080-approved-decisions-resting-on-unfinished-ones/revision-000.md), `approved`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The `relies_on:` field in the frontmatter validator, the decision template and the revision-states section | Done | A missing reason, an unknown id and a self-reference are each rejected, and adding the field to an `accepted` revision is an editorial change |
| 2 | The warning in `check_doc_drift.py` and the `--strict` flag | Done | An unmet reliance is printed with the reliant revision, the target, its state and the reason, and does not change the exit status; `--strict` does |
| 3 | The decisions index note and the project label | Not started | A lineage with a reliance shows "Relies on" with the target's state, and a project whose decision has an unmet one reads "rests on ADR-NNNN (working)", derived and never stored |
| 4 | The first population | Not started | Every approved or accepted revision whose prose cites a `working` lineage for an invariant declares it with a reason, and the warnings the check prints are read once by the maintainer |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] `relies_on:` is validated as ADR 0080 states, and the template and the revision-states section describe it.
- [ ] An unmet reliance is a warning that names the reliant revision, the target, the target's state and the reason, and `--strict` turns it into a failure.
- [ ] The decisions index and the projects index show the reliance and the derived label.
- [ ] The reliances the prose already states are declared, and the warnings the check prints are the maintainer's list of decisions to settle.
- [ ] The behavior is described in [`doc-checks.md`](../topics/engineering/ci/doc-checks.md), and the ADR is `accepted`.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the ADR's Decision, or any revision's status. Adding `relies_on:` to an `accepted` revision carries an `Editorial-Fix:` trailer.
- **Relevant files and interfaces:** [`doc_frontmatter.py`](../../tools/doc_scripts/doc_frontmatter.py) for the field, [`doc_graph.py`](../../tools/doc_scripts/doc_graph.py) for the project `depends_on:` check this one follows, and [`check_doc_drift.py`](../../tools/doc_scripts/check_doc_drift.py).
- **Required checks:** `pre-commit run --all-files`, and `uv run pytest` from `tools/`.

## Risks

- Reliance that is not declared is not checked, so the first population finds only what the prose already says.
- The first run prints a stretch of warnings in every run until they are settled.

## Open items

- Whether [ADR 0049 (Site-loss monitoring)](../decisions/0049-monitoring-that-survives-loss-of-the-site/revision-000.md)'s assumption that ADR 0073 reaches `approved` becomes a `relies_on:`. The assumption stops 0049 being approved at all; a `relies_on:` only warns once it is. Keeping the assumption is the stricter gate, and the choice is the maintainer's at Stage 4.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
