# Docs: where things go

Docs are grouped by artifact type, one directory each:

- **[`topics/`](topics/README.md)** — what is true on `main` now, one
  doc per subject, grouped by what it is about; its index says how the
  groups are chosen. One topic, one doc, cross-referenced rather than
  duplicated — if you're about to explain the same gotcha in a second
  place, link to the first instead. A topic doc describes what is true
  on `main` at every commit, not what a project is still building.
- **[`decisions/`](decisions/README.md)** — why a design was chosen,
  when the reasoning isn't obvious from the code. One lineage per
  problem, one revision per solution tried for it; an `accepted`
  revision's reasoning stays fixed — a changed decision is a new
  revision — while editorial fixes are fine. See
  [`decisions/README.md#editing-a-revision`](decisions/README.md#editing-a-revision)
  for where that line sits.
- **[`architecture/`](architecture/README.md)** — Mermaid diagrams for
  views that cut across multiple topic docs (a system-wide component
  map, an end-to-end data flow). A diagram that only illustrates one
  existing page lives embedded in that page instead.
- **[`projects/`](projects/README.md)** — execution records for
  multi-stage work spanning several PRs: what remains, in what order,
  waiting on what, grouped into initiatives and ordered by dependency.
  Never carries rationale (that's `decisions/`) or current-behavior detail
  (that's a topic doc) — it links to both, and is deleted once the work is
  done and everything durable has been promoted out of it. It can also
  bound what its work may change (`allowed_paths`); see
  [`projects/README.md#scope`](projects/README.md#scope). The generated
  [`project-planning.md`](project-planning.md) orders them across the
  whole repo: projects with an initiative by build order, standalone
  projects, and the open ADRs no project covers yet.

A doc states a figure once, where the file that owns it can be read: a
count of plays, jobs or hosts, a pinned version, a cron period or a
timeout is linked or derived (say what it comes from), not copied, since
a copy goes stale without a check noticing. A figure that is itself the
decision, such as a lifetime an ADR chose, stays in that ADR.

**Every doc's source of truth is the code/config it describes, checked
by [`check_doc_drift.py`](../tools/doc_scripts/check_doc_drift.py)** for
the handful of places that check mechanically (every directory's own
index, with `topics/`'s covering every doc under it at any depth;
`ansible.md`'s playbook table; the molecule scenario matrix; the deploy
play numbering; `ci/pipeline.md`'s job table; every cross-file `#anchor`
reference repo-wide; every `docs/decisions/` or `docs/projects/` path
written anywhere, comments included; and the decision-lineage and
project rules in [`decisions/README.md`](decisions/README.md) and
[`projects/README.md`](projects/README.md)). What a change is allowed to
touch is checked separately, by
[`check_project_scope.py`](../tools/doc_scripts/check_project_scope.py);
deleting a project doc without settling its decision is checked by
[`check_project_close.py`](../tools/doc_scripts/check_project_close.py).
Nothing here enforces the rest by tooling — that's still on whoever's
making the change to keep current in the same PR, the same way a
diagram's topology should change alongside the topology it shows (see
`architecture/README.md`'s note on that).

## Public repo

This repository is public and git history is permanent. No doc, comment,
or commit message records a security incident, a live or recent
vulnerability, or an exposure window — including in ADRs, project risks,
and blockers. If a doc would need those specifics to be useful, leave it
unwritten and raise it privately.
