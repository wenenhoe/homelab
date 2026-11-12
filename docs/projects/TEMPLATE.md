---
id: PROJ-project-name
title: "Project Name"
type: project
status: not-started         # not-started | de-risking | building | done
plan: confirmed             # draft while the decision is working, else confirmed (omit for confirmed)
blocked: false              # true only for an impediment that isn't another project
# blocked_reason: "<the current impediment>"
summary: "<one line; feeds the generated index>"
# decision: ADR-NNNN/N      # the one revision this implements (its label: 0, or 0-b); omit if no ADR is needed
# super_project: <slug>     # optional grouping of projects into an initiative
# allowed_paths:          # optional; the globs this work may change (see README.md#choosing-the-scope)
#   - path/to/thing/**
# depends_on:
#   - project: PROJ-other-project
#     reason: "Concrete prerequisite: work here cannot proceed until it is done"
---

# Project Name

What this project delivers and why it's staged rather than one PR.

## Scope

What changes, and — in one line each — what deliberately doesn't. Name
what the project removes, renames or reshapes, and check it against the
tree before setting `allowed_paths`
([Choosing the scope](README.md#choosing-the-scope)).

## Decision

Link the revision this implements, or say why none is needed. Rationale
lives there, never here.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | ... | Not started | ... |

Stage status is `Not started`, `In progress`, or `Done`. A stage is a change that
merges with its docs: not a spike, an assumption, a decision, an acceptance, a
docs-only change or an operational run (see
[What a stage is](README.md#what-a-stage-is)). Add detail
below only for a stage that needs more than its row to orient someone.

## Acceptance criteria

Observable conditions that mean this project is done.

- [ ] ...

A project that introduces a system (an app, a service a role deploys, or an
external dependency) adds one line per section of its service record
([ADR 0100](../decisions/0100-recording-how-a-system-is-integrated/revision-000.md)),
and replaces the placeholder path with a link to the record:

- [ ] `Dependencies` of `docs/topics/<group>/<system>.md` states what it needs and what needs it.
- [ ] `Data` states what it stores or handles, and which of it is a secret.
- [ ] `Exposure` states what reaches it and what it reaches out to, and with which credential.
- [ ] `Threat model` states what can go wrong, what is done about it, and how that is known.
- [ ] `Observability` states how its failure is noticed and by whom.
- [ ] `Disaster recovery` states what is backed up, how it is restored, and what a rebuild still needs by hand.
- [ ] `Lifecycle` states how it is upgraded, how it is removed, and what it waits on.

A section that does not apply says why in one line, and a fact not yet known
says `Unknown:` and what to check.

## Agent handoff

Omit for work no agent will touch. Stop conditions are in
[`README.md#stop-conditions`](README.md#stop-conditions); they apply
without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced; anything that can't be a glob goes here.
- **Must not change:** ...
- **Relevant files and interfaces:** ...
- **Required checks:** ...

## Risks

Omit if there are none. Could cause rework or delay but blocks nothing now — no live
vulnerability, incident, or exposure window
([`docs/README.md#public-repo`](../README.md#public-repo)).

- ...

## Open items

Genuinely unresolved and carried forward — not a place to restate what a
stage row already says.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
