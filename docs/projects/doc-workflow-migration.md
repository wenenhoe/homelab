---
id: PROJ-doc-workflow-migration
title: "Documentation Workflow Migration"
type: project
status: building
blocked: false
summary: "Move decisions to problem-oriented lineages and projects to the new lifecycle; convert drafts; add agent path-scope enforcement."
decision: ADR-0037/0
---

# Documentation Workflow Migration

Brings the existing docs onto the model in
[ADR 0037](../decisions/0037-decision-and-project-documentation-workflow/revision-000.md).
It is staged because each step is a separate, reviewable change and the
checks must stay green between them.

## Scope

Re-file the flat ADRs, convert the drafts, migrate the five existing
project docs, and build path-scope enforcement. Doesn't rewrite any
`accepted` ADR's reasoning.

## Decision

[ADR 0037](../decisions/0037-decision-and-project-documentation-workflow/revision-000.md).

## Execution plan

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Lineage-aware doc tooling: schema, gates, generated indexes, tests | Done | `check-doc-drift.py` enforces every rule in the decisions and projects READMEs |
| 2 | ADR 0037, both READMEs, the revision and project templates | Done | READMEs describe the model; ADR 0037 is `approved` |
| 3 | Re-file the 36 flat ADRs into 35 lineages | Done | No flat ADR file remains; every link resolves; the lineage index is generated |
| 4 | Drop flat-layout support from the tooling | Done | The doc scripts recognise only the lineage layout |
| 5 | Convert the 15 drafts into `working` revisions | Done | `decisions/drafts/` is gone and nothing links to it |
| 6 | Migrate the five existing projects (split, group, relabel) | Done | Every project doc uses the new statuses; none uses `in-progress` or `blocked` |
| 7 | Path-scope enforcement: `allowed_paths` checked against the PR diff | Not started | A PR touching files outside a `building` project's allowed paths fails CI |

## Acceptance criteria

- [ ] Every decision is a lineage, indexed by topic from frontmatter.
- [ ] No draft, flat ADR, or legacy project status remains.
- [ ] ADR 0037 is `accepted`.
- [ ] Stage 7's check has a unit test that fails when scope is exceeded.

## Agent handoff

- **Allowed to change:** `docs/decisions/`, `docs/projects/`, `docs/README.md`,
  `README.md`, `AGENTS.md`, `.github/scripts/doc_*.py`,
  `.github/scripts/generate-doc-indexes.py`,
  `.github/scripts/check-doc-drift.py`, `tools/tests/doc_scripts/`.
- **Must not change:** the reasoning of any `accepted` ADR revision;
  anything outside the docs tooling.
- **Relevant files and interfaces:** `.github/scripts/doc_frontmatter.py`
  is the schema of record.
- **Required checks:** `pre-commit run --all-files`, and `pytest tools/tests/doc_scripts`.

## Risks

- A re-filing script that rewrites a link wrongly still passes if the
  wrong target exists; review the path map, not just the check result.
