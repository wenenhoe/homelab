---
id: PROJ-project-name
title: "Project Name"
type: project
status: not-started         # not-started | de-risking | building | done
blocked: false              # true only for an impediment that isn't another project
# blocked_reason: "<the current impediment>"
summary: "<one line; feeds the generated index>"
# decision: ADR-NNNN/N      # the one revision this implements (its label: 0, or 0-b); omit if no ADR is needed
# super_project: <slug>     # optional grouping; a track needs it, a phase needs a track
# track: <slug>
# phase: <slug>
# allowed_paths:          # optional; the globs this work may change (see README.md#scope)
#   - path/to/thing/**
# depends_on:
#   - project: PROJ-other-project
#     reason: "Concrete prerequisite: work here cannot proceed until it is done"
---

# Project Name

What this project delivers and why it's staged rather than one PR.

## Scope

What changes, and — in one line each — what deliberately doesn't.

## Decision

Link the revision this implements, or say why none is needed. Rationale
lives there, never here.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | ... | Not started | ... |

Stage status is `Not started`, `In progress`, or `Done`. Add detail
below only for a stage that needs more than its row to orient someone.

## Acceptance criteria

Observable conditions that mean this project is done.

- [ ] ...

## Agent handoff

Omit for work no agent will touch. Stop conditions are in
[`README.md#stop-conditions`](README.md#stop-conditions); they apply
without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced; anything that can't be a glob goes here.
- **Must not change:** ...
- **Relevant files and interfaces:** ...
- **Required checks:** ...

## Risks

Could cause rework or delay but blocks nothing now — no live
vulnerability, incident, or exposure window
([`docs/README.md#public-repo`](../README.md#public-repo)).

- ...

## Open items

Genuinely unresolved and carried forward — not a place to restate what a
stage row already says.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
