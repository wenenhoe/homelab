---
id: ADR-0100
revision: 1
type: adr
title: Recording how a new system is integrated, so its gaps surface when it is added
short: Recording a system's integration
solution: One required-section topic doc per integrated system, linked from its app_catalog entry, checked by check_doc_drift, with a generated disaster-recovery coverage view that shows each system's recovery tier and no drill outcome
summary: How the repository makes a new app, service or dependency state its dependencies, data, exposure, threat model, observability, disaster recovery and lifecycle when it is added, and keeps what a review of them finds out of git history.
topic: documentation-process
status: approved
supersedes: 0
related: [ADR-0028, ADR-0037]
---

# A record per system, and a coverage view that shows no drill outcome

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

## Context

- **Where the answers live today.** The app-adding guide covers wiring, not a
  threat model, an observability story or a restore path, and per-system topic
  docs sit in different groups of `docs/topics/`, so a file name does not
  identify the system it covers.
- **What the repository already derives.** Which apps declare a `backup`, which
  volumes they name and which hosts run them are data in `app_catalog` and
  `host_vars`. Whether a backed-up app has ever been restored is a dated outcome
  of an exercise, which is kept privately. The existing checks do not ask whether
  an entry has any documentation.
- **The same sections fit each kind of system.** Drafts of one record for a
  catalog app, for the certificate issuance and renewal a role installs, and for
  the cloud storage targets each filled the six sections first proposed;
  `Dependencies` was added afterwards, from the practice below. The role's
  `Exposure` is "None" because it has no listener, and for a cloud target the
  section is about what the host sends out and with which credential, which is
  why it names both directions. A draft also needed facts the repository does not
  hold, such as what an app keeps in its data volume, which is why a section may
  say what is unknown.
- **Drill results are private.** What an exercise restored, when, and what it
  found is how the practice was exercised, and
  [`data-classification.md`](../../topics/engineering/data-classification.md)
  keeps that out of this repository. A check kept with the private record joins those results to
  the catalog and reports each system's newest restoring drill against the cadence
  of [ADR 0101 (DR exercise cadence)](../0101-exercising-disaster-recovery/revision-000.md).
  The coverage view therefore shows each system's tier, which the catalog derives,
  and no drill column.
- **A view the apply hooks do not name stops the apply.** With the view missing
  from the list the hooks name, a real `git am` stops on a stale view and makes
  no commit. A patch that carries the view itself conflicts across two series,
  which is why patches leave generated views out.
- **Rebuild order is a dependency question.** A host comes back only if what each
  system needs to start is back first; the rebuild of `security` needed its own
  procedure because two systems each needed the other
  ([ADR 0099 (Rebuilding security from nothing)](../0099-rebuilding-security-from-nothing/revision-000.md)).
  Nothing records, per system, what it needs and what needs it.
- **Established practice.** Operational readiness reviews
  ([AWS Well-Architected, OPS07-BP02](https://docs.aws.amazon.com/wellarchitected/latest/framework/ops_ready_to_support_const_orr.html))
  and production readiness reviews
  ([Google SRE book, chapter 32](https://sre.google/sre-book/evolving-sre-engagement-model/))
  check each service against a standing list of questions. Service catalogs such
  as [Backstage](https://backstage.io/docs/features/software-catalog/descriptor-format)
  hold per-service metadata beside the code, and
  [Shostack's four questions](https://github.com/adamshostack/4QuestionFrame/blob/main/README.md)
  frame a lightweight threat model: what we are working on, what can go wrong,
  what we do about it, and whether that worked. This record borrows their shape,
  claims conformance with none of them, and calls the recurring review an
  **operational readiness review** (ORR).
- **A review's findings are not public.** What an ORR finds is the gaps present at
  the time, which [`docs/README.md#public-repo`](../../README.md#public-repo) keeps
  out of git history. Its questions are the sections and checks below, which can
  be public.
- **Per-system rationale is not an ADR.** An ADR records a contested choice
  ([README](../README.md)); a routine integration has no contest, so it
  needs a home that is not a decision.

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
Gatus endpoint, a command, a record of the exercise kept privately. A claim nothing can confirm is the
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
schedule, its record, and its recovery tier. It is derived and never edited by
hand, and it shows no result of any exercise.

**Readiness.** The project template gains a checklist for a project that
introduces a system, one line per section, linking the record.

**Review.** The records are what a recurring ORR reads, and the questions it
asks are the sections and checks above. Its findings are kept outside this
repository and become public only as the ordinary change that closes a gap. A
gap that no section would have caught is a reason to revise the section set.

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
- **Criticality tiers that scale what a record must hold.** Scorecard products
  grade services bronze, silver and gold. With this few systems the one-line
  "does not apply" does the same job without a second scheme. Lost on weight.
- **Keep a drill-age column in the coverage view.** It was the revision's way to
  show that a backed-up app was never restored. A date per system is the
  outcome of an exercise, and a column of never-restored systems lists the
  gaps, so the check that reports it moved to the private record. Lost on the
  public-repo rule.
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
- The coverage view reads catalog fields by name, so renaming one changes the
  generator.

## Invariants

- No catalog app lacks a record unless it is on the shrinking exemption list.
- A record never holds a rationale an ADR owns, only a link to it.
- The coverage view is derived from the catalog and is never hand-edited. It
  shows no result of an exercise.

## Non-goals

- Writing the records for apps that already exist in this revision's first
  stages; the exemption list carries them.
- Checking that a record's content is true, or counting its `Unknown:` lines.
  The checks prove the sections are present and filled, not correct.
- Running the ORR: when it runs, who runs it and where its findings are kept are
  not decided here.
- Changing the security and reliability defaults in `AGENTS.md`.
- Covering tools that are not deployed (repository scripts, CI helpers).

## Validation

`check_doc_drift.py` for the sections and the link; `check-app-catalog` for the
`doc:` key's shape; a test that the coverage view is current, the way the
other generated views are checked; and the apply hooks' test, which fails when
the view is missing from the list the hooks name. The view no longer reads the fire-drill
doc, so the check that its table names catalog keys is gone with the column.

## Reconsideration triggers

The exemption list stops shrinking, a record's sections are filled with "none"
often enough to show the section set is wrong for a kind of system, or a review,
rebuild or restore drill finds a defect that no section would have caught.
