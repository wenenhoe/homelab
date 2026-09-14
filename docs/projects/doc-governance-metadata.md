# Doc Governance: Frontmatter + Generated Visibility

**Status:** Not started

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
| 1 | Add frontmatter to every existing project/draft/ADR doc | Not started |
| 2 | Generator script: parse frontmatter, regenerate the two README index tables | Not started |
| 3 | Wire the generator into the existing pre-commit hook, alongside `check-doc-drift.py`/markdownlint | Not started |
| 4 | Tag the confirmed NIST subset (RA-3/CM-8/CM-2/CA-7/CP-9/AC-2/IA-2) onto the docs where it's genuinely true | Not started |
| 5 | (Optional) `depends_on` → Mermaid dependency graph, in its own file | Not started |

## Stage detail

### Stage 1 — frontmatter migration

Mechanical but real: every doc under `docs/projects/`,
`docs/decisions/`, and `docs/decisions/drafts/` gets an `id`/`title`/
`type`/`status` header. Sequencing this against the dozen-plus other
projects and drafts already in flight matters more than the
mechanics — decide whether to do it as one pass now or incrementally
as each doc is next touched anyway.

### Stage 2 — generator script

Reads frontmatter across the tree, regenerates the project index table
and the drafts index table exactly — replacing the current
by-hand `str_replace`-per-addition pattern with one script run. Does
*not* touch `check-doc-drift.py`'s existing checks; runs alongside it.

### Stage 3 — pre-commit wiring

Same hook that already runs `check-doc-drift.py` and markdownlint.
Ordering matters: generate first, then lint/drift-check the generated
output, so a bad generation is caught the same way a bad hand-edit is
today.

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
