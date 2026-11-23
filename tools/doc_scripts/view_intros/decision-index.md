# Decision Index

Four generated views of every decision lineage; none is a rules doc. For what
a decision is, its revision states and how to cite one, see
[`decisions/README.md`](decisions/README.md); for what a project is, see
[`projects/README.md`](projects/README.md).

**By number** lays every number out ten to a row: the row is the first
three digits and the column the last, so to open the ADR a chat, a finding
or a commit cites by number, find its cell. A number merged into another
says where it went (`0030 → 0104`), a removed number says what became of it
and links to the ledger, and a dash is a number no lineage holds. A
lineage's name, state and notes are in its row under **By topic**.

**By topic** groups the same lineages by area, in the order of the `topic:`
vocabulary, each row putting the lineage's short name beside the problem it
solves and the solution it has now. On the site each area is a tab.
**Status** is the state of the revision that answers the problem, with the
generation when the lineage has more than one; a revision still being
worked after it is named in Notes, and a lineage merged into another keeps
its old number there (`Formerly ADR-NNNN`).

**Open decisions** is every `approved` or `working` revision, approved first,
with the projects that name it in `decision:` or `also_implements:`.
[`project-planning.md`](project-planning.md#decisions-awaiting-a-project)
lists only the ones no project names.

**History** is every revision that no longer answers its problem: a
`superseded` one with the revision that replaced it, and an `abandoned` one.
