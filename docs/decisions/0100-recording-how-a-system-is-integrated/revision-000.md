---
id: ADR-0100
revision: 0
type: adr
title: Recording how a new system is integrated, so its gaps surface when it is added
short: Recording a system's integration
solution: One required-section topic doc per integrated system, linked from its app_catalog entry, checked by check_doc_drift, with a generated disaster-recovery coverage view
summary: How the repository makes a new app, service or dependency state its threat model, data, exposure, observability, disaster recovery and lifecycle when it is added, instead of leaving those to be found later.
topic: documentation-process
status: working
related: [ADR-0028, ADR-0037]
---

# 0100. Recording how a new system is integrated, so its gaps surface when it is added

## Problem

Adding a system means answering the same questions each time: what an attacker
gains from it, what data it holds, who can reach it, how its failure is seen,
how it comes back after the host is lost, and how it is upgraded and removed.
Nothing makes the answers appear together. They end up in whichever topic doc or
decision the author happened to be editing, and a question nobody asked
(whether its data is backed up, whether a restore was ever exercised) has no
place where its absence is visible. The gap is found when the system is needed
back.

## Context

- **Where the answers live today.** The app-adding guide covers wiring: the
  `docker/` directory, the `app_catalog` entry and `compose_apps`. It does not
  ask for a threat model, an observability story or a restore path.
  Per-system topic docs exist for some systems and sit in different groups of
  `docs/topics/`, so the file name does not identify the system it covers.
- **What the repository already derives.** Which apps declare a `backup`, which
  volumes they name and which hosts run them are data in `app_catalog` and
  `host_vars`. The fire-drill doc records, per rehearsal, which apps were
  restored. Neither is joined to the other anywhere, so whether an app that is
  backed up has ever been restored cannot be read off one page.
- **What the checks cover.** `check_doc_drift.py` already fails on a missing
  index entry, a dead anchor and the decision and project rules.
  `check-app-catalog` validates the shape of a catalog entry. Neither asks
  whether an entry has any documentation.
- **Per-system rationale is not an ADR.** An ADR records a contested choice
  ([README](../README.md)); a routine integration has no contest, so it
  needs a home that is not a decision.

## Decision

Each integrated system has one **service record**: a topic doc with these `##`
sections, in this order.

| Section | Answers |
| :--- | :--- |
| `Threat model` | What an attacker gains from the system and the path to it. |
| `Data` | What it stores or handles, and which of it is a secret. |
| `Exposure` | Who can reach it and through what, including the Tinyauth and TLS defaults in `AGENTS.md`. |
| `Observability` | How its failure is noticed and by whom. |
| `Disaster recovery` | What is backed up, how it is restored, and what a rebuild of its host still needs by hand. |
| `Lifecycle` | How it is upgraded, how it is removed, and what it waits on. |

A section that does not apply says so in one line with the reason; an empty
section is a failure, so absence is a statement. The record links the topic
docs that already own a subject instead of repeating them.

**Linking.** An `app_catalog` entry gains a `doc:` key naming its record, a
path under `docs/topics/`. Several entries may name one record when they are one
system (an agent and its hub). The catalog is already the place for every fact
about an app that does not vary per host, and the record is one of them.

**Checking.** `check_doc_drift.py` fails when a `doc:` path does not exist, or
the doc lacks any of the six sections, has them out of order, or leaves one
empty. An entry without `doc:` fails unless it is on an exemption list kept
beside the check. The list may only shrink: the check fails on an entry that has
a record but is still listed.

**Coverage view.** `generate-doc-indexes` writes a table of every catalog app
with its backed-up volumes, its record, and the newest fire-drill row that
restored it. It is derived and never edited by hand.

**Readiness.** The project template gains a checklist for a project that
introduces a system, one line per section, linking the record.

## Alternatives considered

- **A checklist in the app-adding guide only.** Cheapest, and it is what exists
  in spirit now. Nothing fails when it is skipped, so it drifts. Lost on
  enforcement.
- **The answers as structured fields in `app_catalog`.** One source and
  checkable, but a threat model is prose with links, and the catalog describes
  deployment, not reasoning. Lost on fit.
- **One ADR per integration.** Gives each a lineage and a state, but a routine
  integration has no competing solution, and the lineage rules would turn
  every app into a decision record. Lost on cost for no contest.
- **Derive the record's file name from the app name.** Simple to check, but
  existing records sit in different topic groups, and moving them to fit a name
  would break links for no gain. Lost on churn.

## Assumptions

- **Claim:** The same six sections fit all three kinds of system: a catalog app,
  a service a role deploys to a host (for example the certificate renewal `step_ca_cert` installs), and
  an external dependency (a cloud storage target, a notification channel).
  **Breaks if wrong:** Most sections read "none" for one kind, the rule becomes
  boilerplate, and the kinds need different section sets, which is a different
  decision.
  **Checked by:** drafting one record of each kind in the project's first stage.

- **Claim:** The fire-drill Results table can be joined to catalog apps
  mechanically. Its "Apps covered" cell is free text whose names do not always
  equal catalog keys.
  **Breaks if wrong:** The coverage view shows wrong or missing restores, and the
  table needs a structured column, which changes a doc that is otherwise
  prose.
  **Checked by:** reading the table against the catalog keys in a spike.

- **Claim:** A generated file beyond the three views the apply hooks know can be
  added without the hooks committing a stale copy.
  **Breaks if wrong:** Each applied patch leaves the new view out of date or
  conflicts on it.
  **Checked by:** a real `git am` in a throwaway repository, as
  `test_applypatch_hooks.py` does, with a control that fails without the hook
  change.

## Consequences

- Every new catalog app costs one record. For the apps that exist without one,
  the exemption list is the debt, and it is visible as a list that has to be
  emptied.
- The `doc:` key is a catalog field, so `adding-an-app.md`'s field table, the
  catalog check and `host-vars.md` change with it.
- The apply hooks name their generated views in a fixed list; the coverage view
  joins that list.
- The record states current behavior, so it changes in the same pull request as
  the system does, like any topic doc.

## Invariants

- No catalog app lacks a record unless it is on the shrinking exemption list.
- A record never holds a rationale an ADR owns, only a link to it.
- The coverage view is derived from the catalog and the fire-drill doc and is
  never hand-edited.

## Non-goals

- Writing the records for apps that already exist in this revision's first
  stages; the exemption list carries them.
- Checking that a record's content is true. The checks prove the sections are
  present and filled, not correct.
- Changing the security and reliability defaults in `AGENTS.md`.
- Covering tools that are not deployed (repository scripts, CI helpers).

## Validation

`check_doc_drift.py` for the sections and the link; `check-app-catalog` for the
`doc:` key's shape; a test that the coverage view is current, the way the
other generated views are checked.

## Reconsideration triggers

The exemption list stops shrinking, or a record's sections are filled with
"none" often enough to show the section set is wrong for a kind of system.
