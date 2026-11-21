# Decision Index

Four generated views of every decision lineage; none is a rules doc. For what
a decision is, its revision states and how to cite one, see
[`decisions/README.md`](decisions/README.md); for what a project is, see
[`projects/README.md`](projects/README.md).

**By number** is every lineage in number order, one row each: to open the
ADR a chat, a finding or a commit cites by number, find the row. A lineage
merged into another keeps its old number in Notes (`Formerly ADR-NNNN`).
**Status** is the state of the revision that answers the problem, with the
generation when the lineage has more than one; a revision still being
worked after it is named in Notes.

**By topic** groups the same lineages by area, with the problem each solves
and the solution it has now, in the order of the `topic:` vocabulary.

**Open decisions** is every `approved` or `working` revision, approved first,
with the projects that name it in `decision:` or `also_implements:`.
[`project-planning.md`](project-planning.md#decisions-awaiting-a-project)
lists only the ones no project names.

**History** is every revision that no longer answers its problem: a
`superseded` one with the revision that replaced it, and an `abandoned` one.
