---
id: PROJ-dr-exercises
title: "DR exercises"
type: project
status: building
blocked: false
summary: "Carry out the disaster-recovery exercise cadence: show each system's recovery tier and drill age in the coverage view, run the first quarter of exercises, and accept the decision."
decision: ADR-0101/0
allowed_paths:
  - docs/topics/disaster-recovery/**
  - docs/topics/deploy/adding-an-app.md
  - ansible/inventory/group_vars/all/app_catalog.yaml
  - ansible/scripts/restore_all.py
  - ansible/tests/test_restore_all.py
  - tools/ci/gates/app_catalog_rules.py
  - tools/tests/ci/gates/test_app_catalog_rules.py
  - tools/doc_scripts/**
  - tools/tests/doc_scripts/**
---

# DR exercises

Puts the exercise cadence of [ADR 0101 (DR exercise cadence)](../decisions/0101-exercising-disaster-recovery/revision-000.md)
into practice. The decision, the [exercises page](../topics/disaster-recovery/exercises.md) and the
`recovery_tier` catalog key are merged. What remains is showing the tier and the age of each system's
newest restoring drill in one place, running the cadence for a quarter to see that it can be kept, and
accepting the decision.

## Scope

- The tier and the age of the newest restoring drill, as two columns of the coverage view that
  [`integration-records.md`](integration-records.md) builds.
- The first quarter of exercises, each recorded in the fire-drill results.
- The staged total-loss exercise, now that the host migration is done.
- Accepting ADR 0101, and deleting this doc by its closing checklist.

Not in scope: the coverage view itself (that is `integration-records.md`), and anything about how a review
of the exercises is run or what it finds.

## Decision

[ADR 0101 (DR exercise cadence)](../decisions/0101-exercising-disaster-recovery/revision-000.md), `approved`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The decision, the exercises page and the `recovery_tier` key | Done | ADR 0101 is `approved`, [`exercises.md`](../topics/disaster-recovery/exercises.md) is merged and `check-app-catalog` refuses any tier but `1` |
| 2 | Tier and drill age in the coverage view | Not started | Each catalog app's row in the view shows its tier (the key, else whether it has a `backup`) and the age of the newest fire-drill row that restored it; waits on stage 3 of `integration-records.md`, which builds the view |
| 3 | The first quarter of exercises | Not started | The fire-drill results hold a row for each of: a cloud-source restore, a key-custody check, an app restore of every tier 1 system, a host rebuild and a tabletop; whether the cadence could be kept is written into the next revision of ADR 0101 if it could not |
| 4 | The staged total-loss exercise | Not started | The host migration is done, the chain is run in the isolated block or walked as a tabletop, and the results row says which |
| 5 | Accept the decision | Not started | The view shows tier and age, and ADR 0101 is `accepted`; this doc is deleted by its closing checklist |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [x] `recovery_tier` is a checked catalog key and the exercises page states the rule and the cadence.
- [ ] The coverage view shows each system's tier and the age of its newest restoring drill.
- [ ] The first quarter's exercises are recorded in the fire-drill results.
- [ ] ADR 0101 is `accepted`.

## Agent handoff

Stop conditions are in [`README.md#stop-conditions`](README.md#stop-conditions); they apply without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** any decision revision other than ADR 0101's own; the exercise cadence itself, which only a
  new revision of ADR 0101 changes.
- **Relevant files and interfaces:** [`exercises.md`](../topics/disaster-recovery/exercises.md),
  [`fire-drill.md`](../topics/disaster-recovery/fire-drill.md#results), `tools/doc_scripts/` (the generator that
  writes the views), `ansible/inventory/group_vars/all/app_catalog.yaml`.
- **Required checks:** `pre-commit run --all-files`.

## Risks

Could cause rework or delay but blocks nothing now — no live vulnerability, incident, or exposure window
([`docs/README.md#public-repo`](../README.md#public-repo)).

- One maintainer may not sustain the monthly restore alongside a rebuild every two to three months. ADR 0101
  says a month missed is carried forward and two quarters missed is a reason to revise it.
- The node may not have room for the staged total-loss exercise; the decision falls back to a tabletop of the
  same chain until it does.

## Open items

- Whether the DNS server is a tier 1 system. Clients reach the storage host by name, and the server has no
  backup, so it is tier 3 by derivation. ADR 0101 already names a tier 2 system turning out to be a restore
  dependency as a trigger for a new revision.
- `restore_all.py` reads the on-site copy first and falls back to a cloud copy only when that is unreachable
  or empty, so a cloud-source restore is done by hand. An option that forces a cloud source would make the
  quarterly exercise a command.
- Fetching and decrypting the certificate authority's archive for the bootstrap of the secrets host is by hand
  ([`rebuild-runbook.md`](../topics/disaster-recovery/rebuild-runbook.md#still-done-by-hand)). A script would
  remove the step that is needed before any secret is reachable.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
