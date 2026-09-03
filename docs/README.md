# Docs: where things go

This repo's docs stay flat under `docs/` (see the categorized index in
[`../README.md`](../README.md#further-reading)) plus two subdirectories
for artifact types that don't fit a per-topic page:

- **[`decisions/`](decisions/README.md)** — why a design was chosen,
  when the reasoning isn't obvious from the code. One file per decision,
  numbered, never edited after acceptance (superseded instead).
- **[`architecture/`](architecture/README.md)** — Mermaid diagrams for
  views that cut across multiple topic docs (a system-wide component
  map, an end-to-end data flow). A diagram that only illustrates one
  existing page lives embedded in that page instead.

Everything else is one topic, one doc, cross-referenced rather than
duplicated — if you're about to explain the same gotcha in a second
place, link to the first instead.

**Every doc's source of truth is the code/config it describes, checked
by [`check-doc-drift.py`](../.github/scripts/check-doc-drift.py)** for
the handful of places that check mechanically (README's doc index,
`ansible.md`'s playbook table, the molecule scenario matrix, the deploy
play numbering, `ci.md`'s job table, and every cross-file `#anchor`
reference repo-wide). Nothing here enforces the rest by tooling — that's
still on whoever's making the change to keep current in the same PR,
the same way a diagram's topology should change alongside the topology
it shows (see `architecture/README.md`'s note on that).
