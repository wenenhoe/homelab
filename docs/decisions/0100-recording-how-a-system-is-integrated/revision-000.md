---
id: ADR-0100
revision: 0
type: adr
title: Recording how a new system is integrated, so its gaps surface when it is added
short: Recording a system's integration
solution: One required-section topic doc per integrated system, linked from its app_catalog entry, checked by check_doc_drift, with a generated disaster-recovery coverage view
summary: How the repository makes a new app, service or dependency state its threat model, data, exposure, observability, disaster recovery and lifecycle when it is added, instead of leaving those to be found later.
topic: documentation-process
status: approved
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
- **The same sections fit each kind of system.** Drafts of one record for a
  catalog app, for the certificate issuance and renewal a role installs, and for
  the cloud storage targets each filled all six sections. The role's `Exposure`
  is "None" because it has no listener, and for a cloud target the section is
  about what the host sends out and with which credential, which is why it names
  both directions. A draft also needed facts the repository does not hold, such
  as what an app keeps in its data volume, which is why a section may say what is
  unknown.
- **The fire-drill table joins to the catalog.** Every name in its "Apps covered"
  column is a catalog key, in any case and with an optional parenthetical, so no
  structured column is needed. The join also shows an app that is backed up and
  was never restored, and a restored system that has no `backup` entry because
  its backup is its own, as OpenBao's snapshot is.
- **A view the apply hooks do not name stops the apply.** The hooks name their
  generated views in a fixed list, as does their test. Applied with real
  `git am`, a patch whose extra view is in that list is committed with the view
  regenerated, one after another in a series. With the view missing from the
  list the apply stops on a stale view and makes no commit. A patch that carries
  the view itself conflicts across two series, which is why patches leave
  generated views out.
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
| `Exposure` | What reaches it and what it reaches out to, through what and with which credential, including the Tinyauth and TLS defaults in `AGENTS.md`. |
| `Observability` | How its failure is noticed and by whom. |
| `Disaster recovery` | What is backed up, how it is restored, and what a rebuild of its host still needs by hand. |
| `Lifecycle` | How it is upgraded, how it is removed, and what it waits on. |

A section that does not apply says so in one line with the reason, and one
whose fact is not known yet says `Unknown:` and what to check. Either fills
the section; an empty one is a failure, so absence is a statement and a missing
fact never blocks an integration. The record links the topic docs that already
own a subject instead of repeating them.

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
restored it. It is derived and never edited by hand. A name in the fire-drill
table's "Apps covered" column is a catalog key, in any case and with an optional
parenthetical, and the generator fails on a name that matches no key instead of
guessing.

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
- Checking that a record's content is true, or counting its `Unknown:` lines.
  The checks prove the sections are present and filled, not correct.
- Changing the security and reliability defaults in `AGENTS.md`.
- Covering tools that are not deployed (repository scripts, CI helpers).

## Validation

`check_doc_drift.py` for the sections and the link; `check-app-catalog` for the
`doc:` key's shape; a test that the coverage view is current, the way the
other generated views are checked; and the apply hooks' test, which fails when
the view is missing from the list the hooks name.

## Reconsideration triggers

The exemption list stops shrinking, or a record's sections are filled with
"none" often enough to show the section set is wrong for a kind of system.
