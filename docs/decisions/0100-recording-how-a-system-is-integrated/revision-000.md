---
id: ADR-0100
revision: 0
type: adr
title: Recording how a new system is integrated, so its gaps surface when it is added
short: Recording a system's integration
solution: One required-section topic doc per integrated system, linked from its app_catalog entry, checked by check_doc_drift, with a generated disaster-recovery coverage view
summary: How the repository makes a new app, service or dependency state its dependencies, data, exposure, threat model, observability, disaster recovery and lifecycle when it is added, and keeps what a review of them finds out of git history.
topic: documentation-process
status: superseded
superseded_by: 1
related: [ADR-0028, ADR-0037]
---

# 0100. Recording how a new system is integrated, so its gaps surface when it is added

## Problem

Adding a system means answering the same questions each time: what it needs
and what needs it, what data it holds, who can reach it, what an attacker gains
from it, how its failure is seen, how it comes back after the host is lost, and
how it is upgraded and removed.
Nothing makes the answers appear together. They end up in whichever topic doc or
decision the author happened to be editing, and a question nobody asked
(whether its data is backed up, whether a restore was ever exercised) has no
place where its absence is visible. The gap is found when the system is needed
back.

## Decision

Each integrated system has one **service record**: a topic doc with these `##`
sections, in this order.

| Section | Answers |
| :--- | :--- |
| `Dependencies` | What it needs to start and what needs it (services, secrets, networks), in the order a rebuild must bring them back. |
| `Data` | What it stores or handles, and which of it is a secret. |
| `Exposure` | What reaches it and what it reaches out to, through what and with which credential, including the Tinyauth and TLS defaults in `AGENTS.md`. |
| `Threat model` | What can go wrong (what an attacker gains and the path to it), what is done about it, and how that is known. |
| `Observability` | How its failure is noticed and by whom. |
| `Disaster recovery` | What is backed up, how it is restored, how much data loss and downtime are acceptable, and what a rebuild of its host still needs by hand. |
| `Lifecycle` | How it is upgraded, how it is removed, and what it waits on. |

A section that does not apply says so in one line with the reason, and one
whose fact is not known yet says `Unknown:` and what to check. Either fills
the section; an empty one is a failure, so absence is a statement and a missing
fact never blocks an integration. The record links the topic docs that already
own a subject instead of repeating them.

**Evidence.** A statement in a section names where it can be checked: a test, a
Gatus endpoint, a fire-drill row, a command. A claim nothing can confirm is the
weakest answer, so it is written as `Unknown:`. The checks below confirm the
evidence only where it is derived.

**Derived facts.** What the catalog already declares (a system's hosts, volumes,
routes and whether each is behind Tinyauth, and its backup volumes and schedule)
appears in the coverage view and is not restated. A record holds what the catalog
cannot say.

**Linking.** An `app_catalog` entry gains a `doc:` key naming its record, a
path under `docs/topics/`. Several entries may name one record when they are one
system (an agent and its hub). The catalog is already the place for every fact
about an app that does not vary per host, and the record is one of them.

**Checking.** `check_doc_drift.py` fails when a `doc:` path does not exist, or
the doc lacks any of the seven sections, has them out of order, or leaves one
empty. An entry without `doc:` fails unless it is on an exemption list kept
beside the check. The list may only shrink: the check fails on an entry that has
a record but is still listed.

**Coverage view.** `generate-doc-indexes` writes a table of every catalog app
with its hosts, volumes, routes and their authentication, backup volumes and
schedule, its record, and the newest fire-drill row that restored it. It is
derived and never edited by hand. A name in the fire-drill
table's "Apps covered" column is a catalog key, in any case and with an optional
parenthetical, and the generator fails on a name that matches no key instead of
guessing.

**Readiness.** The project template gains a checklist for a project that
introduces a system, one line per section, linking the record.

**Review.** The records are what a recurring ORR reads, and the questions it
asks are the sections and checks above. Its findings are kept outside this
repository and become public only as the ordinary change that closes a gap. A
gap that no section would have caught is a reason to revise the section set.

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
- Running the ORR: when it runs, who runs it and where its findings are kept are
  not decided here.
- Changing the security and reliability defaults in `AGENTS.md`.
- Covering tools that are not deployed (repository scripts, CI helpers).

## Reconsideration triggers

The exemption list stops shrinking, a record's sections are filled with "none"
often enough to show the section set is wrong for a kind of system, or a review,
rebuild or restore drill finds a defect that no section would have caught.
