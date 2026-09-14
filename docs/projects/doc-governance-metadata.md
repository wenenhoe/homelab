---
id: PROJ-doc-governance-metadata
title: "Doc Governance: Frontmatter + Generated Visibility"
type: project
status: in-progress
summary: "YAML frontmatter across project/decision docs, auto-generated README index tables, and a narrow NIST SP 800-53 mapping for portfolio purposes."
---

# Doc Governance: Frontmatter + Generated Visibility

**Status:** In progress

Adds YAML frontmatter to project/decision docs and auto-generates the
index tables in `docs/projects/README.md` and
`docs/decisions/drafts/README.md` from it, plus a narrow NIST SP
800-53 control mapping for portfolio purposes. Decision and schema are
in
[`metadata-governance-system-evaluate-vs-existing.md`](../decisions/drafts/metadata-governance-system-evaluate-vs-existing.md);
this doc tracks build status only.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | Add frontmatter to every existing project/draft/ADR doc | Done |
| 2 | Generator script: parse frontmatter, regenerate the two README index tables | Done |
| 3 | Wire the generator into the existing pre-commit hook, alongside `check-doc-drift.py`/markdownlint | Done |
| 4 | Tag the confirmed NIST subset (RA-3/CM-8/CM-2/CA-7/CP-9/AC-2/IA-2) onto the docs where it's genuinely true | Not started |
| 5 | (Optional) `depends_on` → Mermaid dependency graph, in its own file | Not started |

## Stage detail

### Stage 1 — frontmatter migration

Every doc under `docs/projects/`, `docs/decisions/`, and
`docs/decisions/drafts/` carries an `id`/`title`/`type`/`status`
frontmatter block ahead of its existing H1; schema (including the
`superseded`/`superseded_by` and project-only `summary` fields added
during this pass) is in
[`metadata-governance-system-evaluate-vs-existing.md`](../decisions/drafts/metadata-governance-system-evaluate-vs-existing.md).
`.config/.markdownlint.yaml`'s `MD025.front_matter_title` is disabled
repo-wide so a frontmatter `title` field and the real body H1 don't
read as duplicate headings.

### Stage 2 — generator script

[`generate-doc-indexes.py`](../../.github/scripts/generate-doc-indexes.py)
reads frontmatter across the tree and regenerates
`docs/projects/README.md`'s Index table and
`docs/decisions/drafts/README.md`'s Open list in place — idempotent,
alphabetical by filename (the prior hand-maintained insertion order
isn't preserved). Doesn't touch `docs/decisions/README.md`'s numbered
ADR index (see Open items) or `check-doc-drift.py`'s existing checks;
runs alongside both.

### Stage 3 — pre-commit wiring

`generate-doc-indexes` is a local hook in
`.config/.pre-commit-config.yaml`, positioned immediately before
`markdownlint-cli2`, both of which run ahead of `check-doc-drift` —
generate, then lint/drift-check the generated output, same as the
table row above says. Documented in
[`docs/ci.md#doc-index-generation`](../ci.md#doc-index-generation).

### Stage 4 — NIST tagging pass

Tag only where the mapping in the decision draft is genuinely true.
Most docs get no `nist_controls` field at all — that's the intended,
correct outcome for a "demo the capability" scope, not an
incompleteness to fix later.

### Stage 5 — dependency graph (optional)

Lower priority than Stages 1-4 — the regenerated tables alone solve
the demonstrated visibility pain. Build only if the tables turn out to
be insufficient once they exist. If built: its own file, never
injected next to `check-doc-drift.py`-parsed content (see the decision
draft's Mermaid-fragility note).

## Open items

- Whether this draft's decision gets promoted to a numbered ADR once
  Stage 1-3 prove out, per this repo's own promotion convention
  (`docs/decisions/README.md`: "Promotion to a real ADR happens once
  the assumptions are resolved") — not done automatically here, since
  promotion also means renumbering and touching that README's own
  index, a deliberate step rather than a side effect of this project
  doc existing.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes) — run
before deleting this doc once every stage is Done.

- [ ] Every `Done` stage's rationale exists as a real ADR, or plainly
      didn't need one.
- [ ] Every `Done` stage's current behavior is in a topic doc.
- [ ] Every open item is resolved-and-promoted or moved to where it
      belongs next.
- [ ] Every cross-reference into this doc elsewhere in the repo is
      updated or removed.
