# Architecture Decision Records

A decision record explains *why* the system is built the way it is, when
the reasoning isn't obvious from the code. It is not a changelog, a bug
log, a plan, or a description of current behavior — those live in git
history, [`projects/`](../projects/README.md), and topic docs
([`docs/README.md`](../README.md)).

Write one when a decision:

- trades off two real options and the choice isn't obvious from the code
  alone (e.g. accepting a security gap because the alternative isn't
  available on a given platform)
- would be expensive to reverse, or someone new would otherwise have to
  reconstruct it from old commits
Skip it for a trivial or cheaply reversible choice, an implementation
detail inside an established pattern, or a temporary experiment. A
question with no chosen solution yet is an
[exploration](../explorations/README.md), not a decision; a `working`
revision is a chosen solution that still has open assumptions.

## Weights

A revision carries `weight: full` (the default) or `weight: light`.

- **Full** when the decision touches a trust boundary, a credential, a path
  that can lose data or block recovery, or would take more than one pull
  request to reverse. Use [`TEMPLATE.md`](TEMPLATE.md).
- **Light** for anything smaller that is still worth a record: a problem,
  the context that decides it, the decision, the option that lost, and what
  would reopen it, using [`TEMPLATE-light.md`](TEMPLATE-light.md). It has no
  Invariants, Non-goals or Validation, and its body stays under the length
  `doc_graph.py` sets; `check_doc_drift.py` fails one that has a forbidden
  section or runs over.
- A choice that would not surprise a reader of the code is not a decision at
  all. It goes in a topic doc or the conventions.

Lineages, states, supersession and editing work the same for both weights.
A light record that turns out to need invariants becomes a new, full
revision. The generated decision index marks a light one.

## Lineages and revisions

One **lineage** per problem: a directory `NNNN-problem-slug/` holding one
file per solution tried for it. The lineage's number identifies the
problem and is never reused. The title names the problem, never the
solution ("Secret storage", not "OpenBao, not a file cache"); each
revision's `solution:` field carries the answer. Use
[`TEMPLATE.md`](TEMPLATE.md).

Files are `revision-NNN.md`, numbered by **generation**: `revision-000.md`
is the original solution and `revision-001.md` is what replaces it.
Solutions that compete to fill the same generation are lettered
**candidates** — `revision-000-a.md`, `revision-000-b.md` — because
neither revises the other. Letters run a, b, c… with none missing and are
required only once a generation has more than one candidate (a lone one is
unlettered or `a`). A revision is named in `supersedes`, `superseded_by`,
and a project's `decision:` by its label: `0`, or `0-b` for a lettered
candidate.

An unlettered revision 0 opens with `# NNNN. <title>`, the lineage's
number and its `title:`; a later or lettered revision opens with a
heading that names its own solution. No revision repeats its state as a
`**Status:**` line in the body: `status:` in the frontmatter is the only
record. `check_doc_drift.py` fails both.

Before creating a lineage, check that:

1. the problem can be stated without naming a solution;
2. a different solution could later answer the same problem;
3. replacing the solution would replace the whole record. If part of it
   would still stand, that part is a second problem — make two lineages.

A lineage is not a topic grouping. Several decisions that make up one
initiative are separate lineages sharing a `topic:`; the generated
[decision index](../decision-index.md#by-topic) groups by it.

## Revision states

| State | Meaning | Reasoning may change? |
| :--- | :--- | :--- |
| `working` | A solution under consideration; open assumptions allowed. | Yes |
| `approved` | No open assumptions; production implementation may begin. | Yes, but a new material assumption returns it to `working`. |
| `accepted` | Implemented and on `main`. | No — editorial fixes only. |
| `superseded` | Replaced by a later revision that is itself `accepted`. It keeps only its frozen sections. | No |
| `abandoned` | A `working` revision no longer pursued. Keep it if the rejected reasoning is useful; delete it if it was only exploration. | No |
| `retired` | The problem no longer exists and nothing replaces the solution. | No |

```text
working ─────► approved ─────► accepted ─────► superseded
   │  ▲            │                │       (a successor is accepted)
   │  └────────────┘                └─────► retired
   │   new material assumption
   └─────► abandoned
```

`accepted` means what most ADR practice means by it — binding and
immutable. `approved` is the state before that: authorized to build, not
yet built.

- Only one revision per lineage is `accepted`. A successor can be
  `working` or `approved` at the same time; the older revision becomes
  `superseded` only once the successor is `accepted`, and the successor
  declares `supersedes:` back. The change that makes the older revision
  `superseded` also cuts it to the sections listed under
  [Superseded revisions](#superseded-revisions).
- A material change to an `accepted` or `superseded` revision is a new
  revision in the same lineage, never an edit. When a superseded ADR is
  referenced from [`nist-800-53-alignment.md`](../topics/engineering/nist-800-53-alignment.md),
  re-check the mapping in the same patch; `check_doc_drift.py` fails
  until it is addressed.
- Competing candidates in one generation stay `working` until one is
  `approved`; the others are then `abandoned`, because approval
  authorizes one design and never two. Letters record the order the
  candidates were written in, not which is preferred.

### Relying on another lineage

A revision whose reasoning holds only while another lineage's boundary does
says so with `relies_on:`, a list of entries each naming the lineage (`adr`)
and the boundary or invariant presupposed (`reason`), in the shape of a
project's `depends_on:`. It is not `related:`, which connects without
depending, and a lineage never relies on itself. Adding it to an `accepted`
revision is a metadata change. The docs check reads declared reliance only,
never `related:` or links in prose, and warns about one whose target is not
settled yet; see
[`doc-checks.md`](../topics/engineering/ci/doc-checks.md#docs-drift-check).

## Assumptions

An **assumption** is an explicitly identified condition that must be true
for the solution to be valid. Only open ones are recorded, under
`## Assumptions`; resolving one folds the fact into Context (or changes
the Decision) and deletes the entry. A revision with any entry can't be
`approved` — `check_doc_drift.py` enforces it — and no project builds on it
meanwhile: a project that names it is a draft plan.

Unknown unknowns are not predicted. When implementation finds a
condition that invalidates the solution, record it as an assumption and
return the revision to `working`; the project stops (see
[`docs/projects/README.md#stop-conditions`](../projects/README.md#stop-conditions)).
An agent may do exactly that — append an open assumption and set
`approved` → `working` — and nothing else to an `approved` or `accepted`
revision, except adding a diagram or table under
[Diagrams and tables](#diagrams-and-tables) and adding or correcting a
short name in a link's text under [Citing a decision](#citing-a-decision).

## Editing a revision

- **Editorial** (typos, a wrong fact that was wrong at the time, a link,
  or a diagram or table that adds no claim — see
  [Diagrams and tables](#diagrams-and-tables)) — any state.
- **Condensing** (removing narration, history, or text another doc
  already holds, without changing what was decided or why) — editorial
  in a `superseded` or `abandoned` revision, since it is a record of what
  was tried and no reasoning is left to protect. In an `accepted`
  revision it is the maintainer's compaction, never part of other work
  ([Compacting accepted records](#compacting-accepted-records)); any other
  edit of that kind is material.
- **A moved file** (a note after a file's first mention in the revision
  that it was renamed or removed: `old (renamed: new)`, `old (removed)`
  or `old (removed; replaced by: new)`) — editorial in any state,
  `accepted` included. It only inserts: the sentence keeps the old name,
  which is what was true when it was written, and the note adds where
  the file went. A table row pairing the old name with the new one needs
  none.
- **Metadata** (`status`, `supersedes`, `superseded_by`, `narrows`,
  `related`, `former_ids`, `relies_on`) — any state; it records lifecycle, not
  reasoning.
- **Material** (the solution, its rationale, its validity conditions) —
  in place while `working` or `approved`; a new revision once `accepted`.

If it is unclear which side a change falls on, treat it as material.

## Diagrams and tables

A revision may carry a Mermaid diagram or a table where structure reads
better than prose: who promotes into what, the order of a handoff, which
identity may reach what. One that only restates what the revision already
says is an editorial change, so it may be added to a revision in any
state, `accepted` and `superseded` included.

- **It adds no claim.** It shows the Decision's mechanism and says
  nothing the prose doesn't. Where the two disagree the prose is the
  record and the visual is the one to fix. A visual that can't be drawn
  without a new claim needs that claim in the prose first, which in an
  `accepted` revision means a new revision.
- **It says what it is.** One sentence before it states that it shows the
  design as this revision decided it, not what runs now. What runs now is
  in the topic docs and [`architecture/`](../architecture/README.md).
- **It fits the content.** A `flowchart` for paths, promotion and
  triggers; a `sequenceDiagram` for a handoff in order; a table for facts
  that enumerate, such as a from-to move or identities against what each
  may reach. Not in `## Alternatives considered`: each option's reason is
  a sentence, which a table cell would turn into a paragraph.
- **It is written by hand, in text.** Plain Mermaid in a fenced block, or
  a markdown table — no images, which don't diff, and no generated
  diagrams, for the reasons in
  [`architecture/README.md`](../architecture/README.md).
- **It renders.** The `mermaid-check` job renders every diagram on a pull
  request that changes markdown, and `python3 -m doc_scripts.check_mermaid`
  from `tools/` does the same by hand with Docker
  ([Mermaid render check](../topics/engineering/ci/doc-checks.md#mermaid-render-check)).
  It fails a diagram that does not render; it says nothing of layout or of
  the Mermaid version GitHub draws with, so look at a new or changed diagram
  rendered too. Write a numbered edge label as `1 .`, not `1.`: a label that
  starts with `1.` is parsed as a markdown list and renders as an error.

## Citing a decision

Link a lineage by its number and short name, so a reader sees what it is
about without following the link:
[ADR 0044 (CD agent trigger)](0044-prod-automation-trigger-and-execution/revision-000-c.md).
Put a revision after the number when it matters:
[ADR 0020 revision 1 (Automation identity scope)](0020-automation-identity-and-access-scope/revision-001.md).
The name is the lineage's `short:` field, which is the same in every
revision and unique across lineages, and `check_doc_drift.py` fails a link
that carries a different one. Renaming it is an editorial change in any
state, made with the links that carry the old name. A link with only the
number still passes: the name is for the reader. Adding or correcting the
name in a link's text is editorial, so an agent may do it in an `approved`
or `accepted` revision.

## Superseded revisions

What is current in a lineage is in its `accepted` revision, so a `superseded`
one keeps only what it decided: its Problem, Decision, Invariants, Non-goals
and Reconsideration triggers sections, as written, with its frontmatter and
title heading. Context, Alternatives considered, Consequences, Validation,
Revision notes and any other section go. The options that lost belong to the
successor's Alternatives, not here.

This is not one of the compacting operations below: it is part of
superseding, made in the same change by whoever sets the successor `accepted`,
agent or maintainer. `check_doc_drift.py` fails a `superseded` revision that
keeps another section, and `uv run python -m doc_scripts.check_doc_drift --fix`
from `tools/` cuts it. The frozen sections cannot change, so the cut cannot alter
what was decided.

## Compacting accepted records

An `accepted` revision cannot be edited, so the decision corpus only grows
unless records are made smaller on purpose. These operations are the
maintainer's, never an agent's working a project, and a pull request that
makes one says which it is.
[`suggest_adr_consolidation.py`](../../tools/doc_scripts/suggest_adr_consolidation.py)
lists candidates and changes nothing, and with `--report` also says whether
too many projects are active.

- **Condense.** Shorten an `accepted` revision in place if
  what it decided is unchanged. Its title, its one-line `solution`, and its
  Problem, Decision, Invariants, Non-goals and Reconsideration triggers
  sections are frozen; Context narration, Consequences and Validation may be
  cut. [`check_accepted_records.py`](../../tools/doc_scripts/check_accepted_records.py)
  compares those parts with the base branch and fails a pull request that
  changes one. A link target, a moved-file note or a short name in a link's
  text is not a change. A typo or a fact that was wrong at the time inside a
  frozen section is an editorial fix: a commit of the pull request carries an
  `Editorial-Fix: <path>` trailer naming the file.
- **Merge.** Records that are one problem become one new lineage, with a new
  number. It carries every Decision point, Invariant, Non-goal and trigger of
  each source, lists their numbers in `former_ids`, and takes over their
  inbound links and `related:` entries in the same change, since a link to a
  deleted record fails the drift check and `former_ids` redirects nothing.
  [`merge_adr_links.py`](../../tools/doc_scripts/merge_adr_links.py) does that
  rewriting once the new record exists and prints the frozen sections it
  touched, which need `Editorial-Fix:` trailers; it deletes and commits
  nothing. The
  source directories are deleted, the NIST mapping that cites a superseded
  source is re-checked as for any supersession, and the options that lost move
  into the new record's Alternatives. It is `accepted` from the start only if
  every source was and no Decision point changed; any change of decision is an
  ordinary revision first.
- **Demote.** A record that is an implementation detail moves to a topic doc
  or the conventions first. Then it is deleted with its inbound links
  rewritten, and its number is listed with where it went in
  [`removed.md`](removed.md).

### Records the report lists that stay separate

The report is advisory, and these pairs and clusters are read and kept apart.
The last column is each record's status when the row was written. The report
leaves a row out until one of its records changes status or goes, and then
lists it to read again; update the column when you have.

| Records | Why they stay separate | Status when read |
| :--- | :--- | :--- |
| ADR 0001 and 0002; 0001 and 0057 | The first two have the same shape but decide different things, host configuration through Ansible and proxy configuration through a checked-in Caddyfile, and each is a reason on its own. 0057 is abandoned. | 0001 accepted, 0002 accepted, 0057 abandoned |
| ADR 0053, 0055, 0056 | Network reach of the coding-agent host, the maintainer's access to it, and the credentials the workstation holds are three boundaries with different owners. 0053 is `working`; 0055 and 0056 are `approved` and cannot merge into an accepted lineage. | 0053 working, 0055 approved, 0056 approved |
| ADR 0056 and 0058 | The credentials the workstation holds, and where operator work runs. 0058 is `working`. | 0056 approved, 0058 working |
| ADR 0044, 0050, 0058 | How prod automation is triggered, how agent-written changes reach it, and where operator work runs are separate problems that cite one another. None is accepted. | 0044 approved, 0050 approved, 0058 working |
| ADR 0065 and 0068 | Where an app's definition merges with host intent, and where backup settings meet shared defaults. Each has its own resolver and its own invariants. | 0065 accepted, 0068 accepted |
| ADR 0107 and 0108 | Whether a pinned artifact is the publisher's, and which image a deploy runs and from where. The second states provenance as a non-goal and relies on the first. | 0107 accepted, 0108 accepted |
| ADR 0096 and 0108 | Hook pinning is `working` and has open assumptions. Re-read it once accepted. | 0096 working, 0108 accepted |
| ADR 0018 and 0023 | Unsealing OpenBao after a restart, and how credential code stores its output. 0018 is `working`. | 0018 working, 0023 accepted |
| ADR 0023, 0109, 0110 | Storage and rotation cadence, expiry, and the R2 admin token. They share a topic and link one another, but each states a different choice with its own triggers. | 0023 accepted, 0109 accepted, 0110 accepted |
| ADR 0037, 0080, 0082 | The documentation workflow, how an approved decision's reliance on an unfinished one is recorded, and how the next project is chosen. 0080 is `approved`. | 0037 accepted, 0080 approved, 0082 accepted |

Nothing is renumbered: a number identifies a problem for good, and git holds
what a deleted record said.

## Partial supersession

When a later solution replaces only part of an earlier revision's scope,
don't edit the old record. The new lineage covers just that slice and
declares `narrows: ADR-NNNN`; the [decision index](../decision-index.md#by-topic) shows "Narrowed by" on the old
one. The sizing check above is what prevents this — it only happens when
an earlier record bundled two problems.

## Projects

An `approved` revision is what a [project](../projects/README.md)
implements, linked by the project's `decision:` field. Several projects
may implement one revision; it becomes `accepted` in the pull request that
closes the last of them, and the resulting behavior is described in topic
docs. See
[`docs/projects/README.md#when-a-project-finishes`](../projects/README.md#when-a-project-finishes).

## Finding a decision

The generated [decision index](../decision-index.md) lists every lineage by
[number](../decision-index.md#by-number) and by
[topic](../decision-index.md#by-topic), the
[open decisions](../decision-index.md#open-decisions) with the projects that
implement them, and the [history](../decision-index.md#history) of superseded
and abandoned revisions.
