---
id: ADR-0080
revision: 0
type: adr
title: Approved decisions that rest on unfinished ones
short: Reliance on working decisions
solution: A declared reliance between decisions, checked as a warning that names every approved or accepted revision whose boundary still rests on a working one
summary: How an approved decision's dependence on a decision that is still being worked out is recorded and surfaced, so the boundary it presupposes cannot change unnoticed.
topic: documentation-process
status: working
related: [ADR-0037, ADR-0044, ADR-0053, ADR-0058]
---

# 0080. Approved decisions that rest on unfinished ones

## Problem

A decision can be approved while a boundary it presupposes is still being
decided in another lineage. The approved decision's invariants then hold only
as long as that other decision does, and nothing says so or notices when it
changes.

What has to be true: when an approved or accepted revision rests on another
lineage's boundary, that reliance is recorded in a form a tool can read, and a
reliance on a revision that is not yet approved is visible to the maintainer
every time the docs are checked.

## Context

The revision states
([`README.md`](../README.md#revision-states)) gate a revision on its own
assumptions: `approved` needs none open in that revision. A project is gated
the same way, on the one revision its `decision:` names. Neither looks at
another lineage. `related:` links lineages, but means only that they are
connected, and carries no claim that one depends on the other.

Prose does record reliance in places. [ADR 0044 revision c (CD agent
trigger)](../0044-prod-automation-trigger-and-execution/revision-000-c.md)
states as an invariant that the coding-agent host has no network path to the CD
agent, and cites [ADR 0053 (Coding-agent network reach)](../0053-network-reach-of-the-coding-agent-host/revision-000.md)
for it. That ADR is `working` and has open assumptions. Several other approved
decisions cite 0053 or [ADR 0058 (Operator work host)](../0058-where-operator-work-runs/revision-000.md),
also `working`, in the same way. If an assumption in one of those breaks, the
approved decisions' invariants stop holding, and the projects building on them
stay `building`, because each is gated only on its own decision.

Two facts shape the fix. `project` files already declare `depends_on:` with a
required reason, and `check_doc_drift.py` already resolves ADR references and
project decisions against revision states, so the pieces exist. And the
backlog is not empty: turning a rule on as a failure would, on the day it
lands, fail the check for decisions that were approved in good faith, and force
either a demotion or an approval of the target in the same change.

## Decision

- **A declared reliance.** An ADR revision may carry `relies_on:`, a list of
  entries with an `adr` id and a `reason` naming the boundary or invariant
  that is presupposed, in the same shape as a project's `depends_on:`. It means
  "this revision's reasoning holds only while that lineage's boundary does". It
  is not `related:`, which stays for connection without dependence. It is
  metadata, so adding it to an `accepted` revision is an editorial change.
- **What counts as met.** The reliant revision's state sets what the target
  must be. A reliant `approved` revision needs a revision of the target
  lineage that is `approved` or `accepted`. A reliant `accepted` revision needs
  one that is `accepted`, because it describes behavior that is already built.
  A `working` reliant revision is not checked, since it is not yet claiming
  anything.
- **A warning first.** An unmet reliance is printed by `check_doc_drift.py` as
  a warning that names the reliant revision, the target, the target's state and
  the reason. It does not change the exit status. A `--strict` flag, and a
  single setting for CI, turns the warnings into failures.
- **Visible where decisions are read.** The decisions index shows
  "Relies on" in a lineage's Notes with the target's state, and the projects
  index and planning table show a project whose decision has an unmet reliance
  as "rests on ADR-NNNN (working)", derived and never stored, like "waiting
  on".
- **The first population is the backlog.** The patch that adds the check also
  adds `relies_on:` to the approved and accepted revisions whose prose already
  cites a `working` lineage for an invariant, each with its reason. The
  warnings it prints are then the list of decisions to settle. Each is settled
  by approving the target, by a revision that drops the reliance, or by
  removing a declaration that was never a reliance.
- **Failing later.** CI switches to `--strict` once the warnings are
  cleared, so a new unmet reliance fails the change that introduces it.

## Alternatives considered

- **Keep it in prose.** It is where the reliance is today. A reader finds it
  only by reading the ADR, and nothing is raised when the target changes.
- **Reuse `related:`.** A revision such as ADR 0044 revision c lists a dozen
  related lineages, most of which it does not depend on. Checking all of them
  would flag every one and be ignored.
- **Fail from the start.** It stops the work of everyone relying on a
  working lineage until the backlog is cleared by an approval or a demotion
  made to satisfy the tool, not by a judgment about the decisions.
- **Demote the reliant revision to `working` automatically.** It makes a
  note in one lineage rewrite the state of another, and the projects building
  on it would stop for a reason no one chose.
- **Gate projects on it now.** A project is `building` on its decision's
  `approved` state. Making an unmet reliance stop it is the same step as
  failing, and waits for the same cleared backlog.

## Consequences

- Authors must say what a decision rests on. A reliance that is not declared is
  not checked, so the check finds only the dependences someone wrote down.
- On the first run the check lists the existing reliances as warnings, which is
  the point, and a stretch of warnings in every run until they are settled.
- The `README.md` revision-states section, `TEMPLATE.md` and the frontmatter
  validator learn the field; `check_doc_drift.py` and the index generators gain
  the check and the two derived labels.
- Settling a warning by approving the target needs that target's open
  assumptions resolved first, which is its own work and its own project.

## Invariants

- An unmet reliance is a warning until CI is switched to `--strict`; it never
  changes a revision's state or a project's status by itself.
- `relies_on:` entries each carry a reason, and name a lineage that exists.
- The check reads declared reliance only, and never infers it from `related:`
  or from links in prose.
- A lineage never relies on itself.

## Non-goals

- Dependences between projects, which `depends_on:` covers.
- Whether the target's decision is right; only its state.
- Changing the meaning of `related:`.

## Validation

- Unit tests over fixture lineages: a reliant `approved` revision with a target
  that is `working`, `approved` and `accepted`; a reliant `accepted` revision
  with a target that is `approved` and `accepted`; a `working` reliant revision
  that is never checked; a missing reason, an unknown id and a self-reference
  each rejected by the validator.
- A test that the warning does not change the exit status, and that `--strict`
  does.
- Generator tests for the Notes text and the project label.
- The docs check run on the repository after the first population, with its
  warnings read once by the maintainer.

## Reconsideration triggers

- The warnings are cleared: switch CI to `--strict`.
- The warnings are being ignored or are mostly noise: change what counts as
  reliance before making them fail.
- A project gate is wanted on reliance: extend the lifecycle table, in a revision.
