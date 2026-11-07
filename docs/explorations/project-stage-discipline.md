---
id: EXP-project-stage-discipline
title: "What should a project's status and stage table promise, and what enforces it?"
type: exploration
status: open
summary: "Project status follows the linked decision but not the stage table, and spike stages appear in projects of every status, so the status says little about the work."
topic: documentation-process
related: [ADR-0037, ADR-0080, ADR-0082]
---

# What should a project's status and stage table promise, and what enforces it?

A project carries a status (`not-started`, `de-risking`, `building`, `done`)
and a stage table. The status is checked against the linked decision's state;
nothing checks it against the stage table. As a result the status can say one
thing and the table another, and a spike stage can sit in a project of any
status.

## What bears on it

- The check ties `de-risking` to a `working` revision and `building` to an
  `approved` one. A new `not-started` project needs an `approved` revision or
  none. The lifecycle table in
  [`docs/projects/README.md`](../projects/README.md#lifecycle) says
  `de-risking` is for throwaway spikes and reading code.
- Of the 39 project docs at the time of writing, six disagree with their own
  stage table: five are `de-risking` with no stage started, and one is
  `not-started` with a stage Done.
- Thirteen projects have a spike or a verification as stage 1. Five of those are
  `de-risking`, six are `not-started` and one is `building`. A spike stage in a
  project on an `approved` revision means either that approval came before an
  assumption was resolved, or that the spike is ordinary build work under another
  name.
- `de-risking` is implied by a `working` revision: a project has to clear the
  revision's open assumptions before it builds. A spike stage in a project on a
  `working` revision restates that.
- A spike is how an open question is answered when the answer needs running
  something. Today its only home is a project on a `working` revision, so an
  undecided question with a spike has to be filed as a decision first. An
  exploration cannot be linked from a project, because it is deleted when it
  ends.
- A project without `decision:` is allowed, and an exploration may end by
  opening one for work that needs no decision.

## Options

1. **Derive the status from the table and the decision.** `not-started` when no
   stage has started, `de-risking` when the decision is `working`, `building`
   otherwise, with the check failing a stored status that disagrees. Cheap, and
   it removes the six mismatches, but it makes the field redundant.
2. **Keep the status as authored and check it against the table.** Fails
   `not-started` with a started stage, and `building` or `de-risking` with none
   started. The author still states intent, and the check only catches drift.
3. **A spike stage is valid only while the decision is `working`.** When the
   revision is approved, a spike stage left in the table fails the check. A
   spike that is real work after approval is named for what it builds.
4. **A spike for an undecided question is a project without a decision.** It
   states the question in its own scope and ends by writing the decision. No link
   to an exploration is needed, and the exploration is deleted in the pull
   request that opens the project.
5. **Leave it.** The status keeps meaning "what the decision allows" and the
   stage table stays free text. Costs a small, constant mismatch.

Options 2 to 4 combine: they cost three small checks and two sentences in the
lifecycle table.

## Leaning

Options 2, 3 and 4 together, with option 1 left out so the status stays a
statement of intent. What would change it: a stage table that gets a machine
status of its own, which would make option 1 the simpler route.
