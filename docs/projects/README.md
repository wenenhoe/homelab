# Projects

A project is a temporary execution record for multi-stage work: where
the build stands, what remains, and what it waits on. It never owns
rationale (that's an [ADR](../decisions/README.md)) or current behavior
(that's a topic doc), and it is deleted once everything durable has a
home.

Topic docs describe `main` at every commit. A stage that has merged is
current behavior even while its project is unfinished — update the topic
doc in the same PR. The project only tracks what is left.

## When this is the right artifact

A genuinely multi-stage, multi-PR piece of work with a real stage table —
more than one row that isn't "done in this PR." A single-PR feature,
however large, doesn't qualify: it gets a topic doc, or an ADR if it
involved a contested choice. A project needs an ADR only when it
implements a real decision; otherwise it has no `decision:` and nothing
gates it.

## Hierarchy

- **Super-project** — a large initiative that needs several projects. A
  label (`super_project:`), not a document; see
  [Super Projects](../project-planning.md#super-projects).
- **Project** — the smallest independently manageable and closable unit;
  one doc.
- **Stage** — a sequential build step inside one project. Numbering is
  local to that doc.

No level is required; don't add one for naming's sake. Decompose a broad
initiative top-down, or add a `super_project` label once existing
projects turn out to be coupled — both are fine.

The generated [Super Projects](../project-planning.md#super-projects) view
groups an initiative's projects and reads them by dependency depth, then by
file name. An order that is not a dependency is not recorded: if one project
cannot start until another is done, declare it; if it merely goes first, say
so in the stage prose.

Hierarchy says where work belongs; dependency says what must finish
first. Declare `depends_on` (`project:` and `reason:`) only when work
here cannot proceed until that project is done — not for relatedness, a
shared ADR, similar subject, or preferred order. The [project-planning view](../project-planning.md)
shows "waiting on" while the predecessor still exists; remove the entry in the
change that deletes the finished predecessor, or the checker fails on a
dangling one.

## Lifecycle

| Status | Meaning | Linked `decision:` revision must be |
| :--- | :--- | :--- |
| `not-started` | Nothing underway. | `approved` for a new project; `working` or `approved` for one already waiting |
| `de-risking` | Waiting on the decision's open assumptions, which are settled in the decision; every stage is `Not started`. | `working` |
| `building` | Production implementation is authorized. | `approved` |
| `done` | Everything implemented and merged. | `accepted`, or `approved` while another project still names it |

`check_doc_drift.py` enforces the last column, so a revision that drops
back to `working` stops any project `building` on it. It also checks the
status against the stage table: `not-started` or `de-risking` with a stage `In
progress` or `Done`, or `building` with every stage `Not started`, fails. A
doc with no stage rows is not judged. A stage that is not a build change fails
unless it is `Done`: a spike, an assumption, a decision, an acceptance, a
docs-only change or an operational run (see [What a stage is](#what-a-stage-is)). A project without
`decision:` isn't gated. Several projects may name one revision; it stays
`approved` until the last of them closes (see
[When a project finishes](#when-a-project-finishes)).

A project builds on a settled decision. One whose `decision:` revision is still
`working` is a draft plan, `plan: draft`, which exists for sizing and the
roadmap and is not a commitment; the drift check requires the field there. Its
assumptions are settled in the decision, not in a stage, and a question no
decision covers yet stays in an [exploration](../explorations/README.md) until
it is approved. A project's `plan` is `draft` or `confirmed`; absent counts as
confirmed. Read the stage table again against the approved decision before
building starts: the change that sets `status: building` also sets `plan:
confirmed` (or drops the field), sets `allowed_paths`, and either changes the
Execution plan or carries a `Plan-Confirmed: <project doc path>` trailer on a
commit when the table needed no change.
[`check_project_start.py`](../../tools/doc_scripts/check_project_start.py)
fails a change that adds a project on a decision that is not `approved` unless
it is a draft plan, and one that sets a project `building` without those; it reads only the docs the change adds for the first, so a project already
waiting on a `working` revision is left alone until that revision is approved
or the project is withdrawn
([When a project finishes](#when-a-project-finishes)). More than the limit in
[`generate_doc_indexes.py`](../../tools/doc_scripts/generate_doc_indexes.py)
of projects at `building` or `de-risking` at once draws a warning from the
generator: finished work comes before new work.

`blocked: true` with a `blocked_reason` is a flag, not a status: a
current impediment that isn't another project (hardware, an external
service). Waiting on a project is derived from `depends_on`, and so is
"ready": the project-planning view's Blocker cell is `—` for a `not-started` project when its
decision revision is `approved` (or it has no `decision:`), it is not blocked,
and no project it depends on remains. Neither is a status, so neither needs
an edit when it changes. A `not-started` project that is not blocked and
waits on no project, but whose decision revision is not yet `approved`,
reads "waiting on" that revision, derived the same way. A project whose
decision revision declares a `relies_on:` that is not yet met reads "rests on
ADR-NNNN (working)", naming the target and its state, in the same cell and
derived the same way; it never stops the project by itself
([ADR 0080 (Reliance on working decisions)](../decisions/0080-approved-decisions-resting-on-unfinished-ones/revision-000.md)). A risk —
something that could cause rework but blocks nothing now — goes in the
doc's Risks list instead.

The generated views derive one more thing from the same fields.
**Unblocks** is the number of existing projects that wait on a project,
directly or through a chain of `depends_on`. It is not stored, and no field
carries a priority
([ADR 0082 (Choosing the next project)](../decisions/0082-choosing-which-project-to-take-up-next/revision-001.md)).

## What a stage is

A stage is a change that merges together with its docs, and its exit condition is
something a check or a reader can see. Some work is not a stage, and the drift
check fails a stage titled for it until it is `Done`:

- **A spike, or resolving an assumption.** Assumptions live in the decision and are
  settled there.
- **Writing or approving a decision.** A question with no decision is an
  exploration.
- **Accepting the decision.** That is the closing checklist.
- **A docs-only change.** Docs travel with the code they describe.
- **An operational run,** such as a rollout or a drill. It is an acceptance
  criterion.

A project is the smallest unit that can be finished and deleted without a stage of
another project having to run first. Declare `depends_on` for a project that must
be built before this one can be applied or live. Projects that name one revision
and are chained by `depends_on` are one project unless something outside the work
separates them, such as hardware, or another project depends on the first alone.

## What goes in one

The shape of [`TEMPLATE.md`](TEMPLATE.md): scope, the decision it
implements, a stage table (`Not started` / `In progress` / `Done`, each
with an exit condition), acceptance criteria, agent handoff, risks, and
open items. Update the stage table at the start and end of each PR that
works a stage. If a stage's prose starts explaining why X over Y, stop
and write or extend the ADR instead.

A project's `decision:` is singular and gating — it's the one
`check_doc_drift.py` checks against the Lifecycle table above. A
stage's exit condition can still set a *different* lineage's revision
to `accepted` as a side effect; when it does, add that revision to
`also_implements:` (same format as `decision:`, e.g.
`ADR-0050/0`) and say so in prose where the stage is described —
[`coding-agent-access-path.md`](coding-agent-access-path.md)
(`decision: ADR-0055/0`, `also_implements: [ADR-0050/0]`, whose
closing PR sets ADR 0050 to `accepted`) is the existing example.
`also_implements:` doesn't gate anything — `check_doc_drift.py` only
confirms each entry resolves to a real revision, and the close check reads it
(see [When a project finishes](#when-a-project-finishes)) — it exists so
[`project-planning.md`'s "Decisions awaiting a project"](../project-planning.md#decisions-awaiting-a-project)
view can tell this ADR is covered without scanning every project's
prose for a mention. It also exempts that revision, and the one it
supersedes, from `allowed_paths` (see [Scope](#scope)). Don't confuse
this with a project that simply has
no `decision:` yet because nothing is `approved`: no ADR is being
carried out there, one just isn't chosen yet, and it has neither field
set.

## Stop conditions

Whoever is implementing — human or agent — stops and hands the decision
to a human when:

- implementing needs a change to the linked revision's Decision;
- a new material assumption turns up;
- an acceptance criterion can't be satisfied;
- a new dependency or security boundary appears;
- the scope needs to grow, which includes a file outside `allowed_paths`
  (see [Scope](#scope)).

For the first two, record it (an agent's only permitted ADR edits are in
[`docs/decisions/README.md#assumptions`](../decisions/README.md#assumptions))
and stop; don't improvise around it.

## Scope

A project doc declares `allowed_paths`: the file globs its work may
change. It is set once, in the change that sets `status: building`, which
the drift check requires; a project that is not building yet may omit it.

```yaml
allowed_paths:
  - tools/doc_scripts/doc_*.py
  - tools/tests/doc_scripts/**
```

`*` and `?` stay inside one directory; `**` crosses directories. A
pattern that matches every file (`**`, `*`) is rejected, since it would
bound nothing.

A change is tied to a project by working its doc, which any change that
works a stage already does: it changes the doc's frontmatter or the status
of a stage in its Execution plan table, or it deletes the doc. Editing
the doc's prose or links, as a wording or link sweep across every doc
does, doesn't tie the change to it. Every other file that change touches must
match `allowed_paths`, apart from what the workflow itself produces:
project docs, the generated decision index and project-planning view
(a status change regenerates both), and the decision revisions its
close edits: the one `decision:` names, each one in `also_implements:`,
and the revision each of those supersedes, since accepting a successor
marks its predecessor `superseded`. The predecessor is the one named by
the `supersedes:` the revision has on the base branch, so a change can't
exempt a file by adding that field. A
change that works no project doc isn't project work and isn't checked.
One that touches several scoped projects gets the union of their scopes.

The scope in force is the one on the base branch, not the one in the
change, so widening `allowed_paths` is its own change, reviewed before it
is used. A project doc that is new in a change has no scope yet.

This is the mechanical half of the "scope needs to grow" stop condition:
work that needs a file outside `allowed_paths` fails the check and stops.
Omit the field for work no agent will touch. It is path-level only: it
can't tell whether an edit inside an allowed file is the permitted one,
and a change that never touches its project doc isn't bounded. How and
where it runs is in
[`docs/topics/engineering/ci/doc-checks.md#project-scope-check`](../topics/engineering/ci/doc-checks.md#project-scope-check).

### Choosing the scope

A project's scope is every file its pull requests edit, the one that
closes it included. Widening it is its own change, so each file found
late costs a pull request. Derive the scope from the project instead of
from memory of where the work lives:

1. **Name what each stage changes.** Every path in `allowed_paths` traces
   to a stage's exit condition or an acceptance criterion, which names the
   file, role or workflow it edits. A path that traces to neither is new
   work: add the stage or criterion in the change that widens the scope, or
   make it a separate project.
2. **Search for what the project removes, renames or reshapes.** For each
   such name (a product, a pin, a variable, a key), search the tree. A file
   that mentions it is in scope, or is named under "Not in" with the
   reason. Don't list the places you remember: the ones you forgot are the
   ones that stop the work.
3. **Walk the closing pull request.** It deletes the project doc, so every
   file that names the doc changes too. The decision revisions it edits are
   [exempt](#scope). The NIST alignment page is not: it changes when it
   links the revision being superseded. Neither are the topic docs that
   will describe the new behavior, nor a new topic doc's row in
   `docs/topics/README.md`.
4. **Shape the entries.** A directory glob for a component the project
   changes, an exact file for anything peripheral. Never an exact file
   inside a component the project already changes: the next file in that
   directory is the next widening.

[`suggest_project_scope`](../topics/engineering/ci/doc-checks.md#scope-suggestions)
runs the searches behind steps 1 to 3 and prints the entries that are
missing. What a hit means is still the author's call.

## Public repo

Risks, blockers, and any evidence recorded here follow the rule in
[`docs/README.md#public-repo`](../README.md#public-repo): no live
vulnerability, incident, or exposure window.

## When a project finishes

Once every stage is done and everything durable has a home, delete the
doc rather than trimming it to a pointer or archiving it — what's left is
either current-state fact (which belongs in a topic doc) or build
narrative (which git and the PRs already hold). Run the checklist first;
skipping it is how a real fact gets lost instead of promoted.

A project that names only `working` revisions is withdrawn, not closed:
delete the doc, with no checklist, since it built nothing and its stage plan
is only a draft. The revision then shows in
[Decisions awaiting a project](../project-planning.md#decisions-awaiting-a-project)
until a project is opened for it again. A doc that names any other revision
closes as described below.

A revision that other projects still name in `decision:` stays
`approved`: this project isn't the last, so it closes without touching
the revision. The last project to name a revision sets it `accepted` in
the PR that deletes its doc, which asserts that the whole Decision is
implemented. If part of it isn't, that PR adds a `not-started` successor
project for the remainder, which also means this one isn't the last.
A project names a revision in `decision:` or in `also_implements:`, and a closing
project's `also_implements:` entries are judged like its `decision:`: each must be
`accepted` afterwards or named by a project that remains. A merge of two projects
with different unaccepted decisions keeps one in `decision:` and lists the other
in `also_implements:`.
[`check_project_close.py`](../../tools/doc_scripts/check_project_close.py)
fails a PR that deletes a project doc and does neither; see
[`docs/topics/engineering/ci/doc-checks.md#project-close-check`](../topics/engineering/ci/doc-checks.md#project-close-check), and
[ADR 0037 revision 3 (Decision and project workflow)](../decisions/0037-decision-and-project-documentation-workflow/revision-003.md)
for the reasoning.

That PR condenses the revision first, while it is still `approved` and can
be edited in place: it removes narration, history and text a topic doc now
holds, without changing what was decided or why. Once the revision is
`accepted`, only the maintainer's compaction pass can shorten it
([Compacting accepted records](../decisions/README.md#compacting-accepted-records)),
so a revision left heavy with detail that mattered only while building stays
heavy until then. Nothing checks that it was done, so it is on the closing
checklist.

The revision this one supersedes is cut to its frozen sections in the same PR
([Superseded revisions](../decisions/README.md#superseded-revisions)); the
drift check fails the PR otherwise.

### Closing checklist

This is the only copy: each project doc's `## Closing checklist` points
here.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or
      named by a successor project.
- [ ] If this PR sets the linked revision `accepted`, condense it first:
      remove narration, history and text a topic doc now holds, without
      changing what was decided or why. Once `accepted`, only the
      maintainer's compaction pass can shorten it.
- [ ] If that revision supersedes another, the superseded one is cut to its
      frozen sections (`check_doc_drift --fix`).
- [ ] The linked revision is `accepted` (set in the PR that closes the
      last project naming it), another project still names it, or there
      is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc, not only here.
- [ ] Every open item is resolved and promoted, or moved to the ADR or
      project it belongs to next.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
- [ ] No code comment, message or topic doc still names this project's
      stages, phases or tracks.
