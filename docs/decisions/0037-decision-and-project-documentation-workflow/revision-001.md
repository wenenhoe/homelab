---
id: ADR-0037
revision: 1
type: adr
title: "Recording decisions, tracking execution, and keeping docs true"
short: Decision and project workflow
solution: "also_implements: as a validated, non-gating frontmatter field, plus a generated view of open ADRs no project covers"
summary: "How why, what-remains, and what-is-true-now are kept apart, extended to close a visibility gap the original method left open."
topic: documentation-process
status: superseded
superseded_by: 2
supersedes: 0
related: [ADR-0050, ADR-0055]
---

# Formalizing which ADRs a project covers, and surfacing the ones none does

## Decision

Add `also_implements:` to a project doc's frontmatter: a list of
revision references in the same format as `decision:` (`ADR-0050/0`),
naming a lineage this project's stages complete as a side effect,
distinct from the one it's gated on. `check-doc-drift.py` (renamed: `check_doc_drift.py`) validates
each entry resolves to a real lineage revision, the same check
`decision:` already gets — but `also_implements:` never enters
`PROJECT_DECISION_GATE`; it records a fact, and gates nothing.

Add a generated table to a new topic doc,
[`docs/project-planning.md`](../../project-planning.md): every ADR
lineage with an open revision that appears in no project's `decision:`
or `also_implements:`. Move the existing `## By initiative` table there
too — a planning/build-order view, not a rule, and it doesn't belong in
[`docs/projects/README.md`](../../projects/README.md) any more than the
new table would.

`generate-doc-indexes.py` (renamed: `generate_doc_indexes.py`) grows a fourth target file; the `## Index`
table an agent may need to reference for `check-project-scope.py`'s (renamed: `check_project_scope.py`)
reverse-link check stays exactly where it is, in
`docs/projects/README.md`.
