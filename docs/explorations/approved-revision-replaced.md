---
id: EXP-approved-revision-replaced
title: "How should an approved revision be shown once an approved successor replaces it?"
type: exploration
status: open
summary: "What the lifecycle and the generated views do with a revision that is still approved while an approved revision of the same lineage names it in `supersedes`, before either is accepted."
topic: documentation-process
related: [ADR-0037, ADR-0053]
---

# How should an approved revision be shown once an approved successor replaces it?

A lineage can hold an `approved` revision and an `approved` successor that declares `supersedes:` back, because the older one becomes `superseded` only once the successor is `accepted`. Until then the older one reads as a second design waiting to be built. The question is whether the lifecycle or the views should say that it has been replaced.

## What bears on it

- **The rule.** [`decisions/README.md`](../decisions/README.md#revision-states) lets a successor be `working` or `approved` beside the older revision, which stays as it is until the successor is accepted. `abandoned` is for a `working` revision, and the README names no state for an approved one that is replaced.
- **A live case.** ADR 0053's revisions 0 and 1 are both `approved`, and revision 1 declares `supersedes: 0`. A project names revision 1 and none names revision 0.
- **What the views say.** The planning view lists the lineage under "Decisions awaiting a project" as "Undecided between" the two, though one replaces the other. The open-decisions table lists revision 0 with no project.
- **What the tests fix.** An existing test requires an `approved` revision with a `working` successor to show both statuses, so the views already treat a successor in flight as a second open revision on purpose.
- **Competing candidates differ.** Letters mark solutions that compete for one generation, and approving one abandons the rest. A successor in the next generation does not compete with its parent.

## Options

- **Leave it.** The wording of the view is the only cost, and a reader has to know the rule.
- **Teach the views.** Once the successor is `approved`, the awaiting-a-project view and the "undecided" wording leave out a revision that an open successor names in `supersedes`, and the open-decisions table notes it. No state changes. A `working` successor still shows both, as the test requires.
- **Let an approved revision be abandoned when its approved successor replaces it.** The state is then in the front matter, at the price of a new transition in the state machine and a rule for what the abandoned record keeps.
- **Delete the older revision when the successor is approved.** Git holds it and nothing links to it, but the README allows deleting only an `abandoned` record that was exploration.

## Leaning

Teach the views: it changes no state and no rule of the lifecycle. What would change it: a case where the older revision is still wanted as a fallback after the successor is approved.
