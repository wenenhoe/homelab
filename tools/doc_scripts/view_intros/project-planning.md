# Project Planning

Five generated, cross-cutting views; none is a rules doc. For what a
project is and its lifecycle, see [`projects/README.md`](projects/README.md);
for what an ADR is and its revision states, see
[`decisions/README.md`](decisions/README.md); for every ADR by number and
topic, see [`decision-index.md`](decision-index.md).

**Unblocks**, in every table of projects, is the number of existing
projects that wait on that one, directly or through a chain of
`depends_on`; `—` means none does. It counts projects, not effort or
urgency.

**Status and Blocker**, in every table of projects, are two cells. Status is the
lifecycle status. Blocker says what stands in the way: `blocked:` and the
reason, `waiting on` the projects it depends on that still exist, or `waiting
on` its decision revision, named by its short name, when that is not yet
approved; more than one are joined with a semicolon. `—` means nothing does, so a not-started project with
`—` can be started. Neither cell is stored, per
[ADR 0082 (Choosing the next project)](decisions/0082-choosing-which-project-to-take-up-next/revision-002.md).

**Covers**, in every table of projects, is the project's `summary:`.

**Roadmap** has one row per initiative, in the order kept in
[`projects/README.md`](projects/README.md#initiatives), then a last row for
projects with no initiative. The order ranks initiatives and says where to
look first; work in any row that has a startable project. A project is in
**In progress** when it is building or de-risking, in **Startable** when it is
not started and its Blocker is `—`, and in **Waiting** when it is not started
and something stands in the way. A cell lists projects by dependency depth,
then file name, each with its Unblocks count when that is not zero; a done
project is not shown.

**Super Projects** groups every project that belongs to one
(`super_project:` is set) by build order — projects by dependency depth,
then by file name, per
[`projects/README.md`'s Hierarchy section](projects/README.md#hierarchy).
A repeated initiative name is blanked after its first row so the table
reads as one block per initiative.

**Projects** is every project with no `super_project` — the complement
of the view above, with the same columns. It lists building projects
first, then de-risking, not started and done, each by file name.

**Decisions awaiting a project** lists every ADR lineage with an open
(`working`/`approved`) revision that appears in no project's
`decision:` or `also_implements:` — see
[ADR 0037 revision 1 (Decision and project workflow)](decisions/0037-decision-and-project-documentation-workflow/revision-001.md)
for why those two fields specifically. A row here isn't automatically a
gap: some are correctly undecided and can't have a project yet, some
are single-PR-sized and don't need one, and this table can't see a
project that references the lineage only in prose without either field
set. It narrows where to look; it doesn't replace looking. Approved
revisions are listed first: one that no project names is the gap that
calls for a project, while a working one still has to be settled.

**Open explorations** lists every question in
[`explorations/`](explorations/README.md) by file name, with its question; it
shows no dates, so the view depends on the tree alone.
