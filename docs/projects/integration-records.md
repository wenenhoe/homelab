---
id: PROJ-integration-records
title: "Integration records"
type: project
status: building
blocked: false
summary: "A required-section topic doc for every integrated system, linked from the app catalog and checked, with a generated disaster-recovery coverage view."
decision: ADR-0100/0
allowed_paths:
  - docs/topics/**
  - docs/projects/TEMPLATE.md
  - ansible/inventory/group_vars/all/app_catalog.yaml
  - tools/ci/gates/app_catalog_rules.py
  - tools/doc_scripts/**
  - tools/tests/doc_scripts/**
  - tools/tests/ci/gates/**
  - .githooks/**
---

# Integration records

Gives every system the repository integrates one topic doc that states its
threat model, data, exposure, observability, disaster recovery and lifecycle,
and makes a missing or empty one fail a check. It is staged because the rule
needs a design spike first, the check and the generated view touch tooling that
every later patch depends on, and the existing apps need records written one
group at a time.

## Scope

- The `doc:` key on `app_catalog` entries, its check, and the exemption list.
- The section check in `check_doc_drift.py`.
- The generated coverage view and the apply-hook change it needs.
- The readiness checklist in the project template, and the field table in the
  app-adding guide.
- Records for the apps on the exemption list, until it is empty.

Not in scope: the content of any record beyond its sections, a check that a
record is true, and tools that are not deployed.

## Decision

[ADR 0100 (Recording a system's integration)](../decisions/0100-recording-how-a-system-is-integrated/revision-000.md)
holds the section set, the link, the checks and the view. It is `approved`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike: one record of each kind (catalog app, role-deployed service, external dependency) and a trial join of the fire-drill table to catalog keys | Done | The three assumptions in ADR 0100 are settled and folded into its Context, and it is `approved`. |
| 2 | The `doc:` key, its shape check, the section check and the exemption list | Done | A new catalog entry with no record, a missing section or an empty section fails; an entry with a record that is still listed fails; every existing app passes. |
| 3 | The generated coverage view and its apply-hook support | Not started | The view lists every catalog app with its volumes, record and newest restoring drill; the hooks and their test read one list of generated views, and a throwaway `git am` leaves the view current. |
| 4 | The readiness checklist and the app-adding guide | Not started | The template lists one line per section; the guide's field table names `doc:`. |
| 5 | Records for the exempt apps, one topic group per pull request | Not started | The exemption list is empty and is removed with its check. |

## Acceptance criteria

- [ ] Every `app_catalog` entry names a record whose seven sections are present,
  in order and filled.
- [ ] The coverage view is generated and a stale one fails a check.
- [ ] The project template carries the readiness checklist.
- [ ] ADR 0100 is `accepted`.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced. The
  `.githooks/` entry is for adding the coverage view to the apply hooks' list
  only.
- **Must not change:** the security and reliability defaults in `AGENTS.md`;
  any decision revision other than ADR 0100's own.
- **Relevant files and interfaces:** `ansible/inventory/group_vars/all/app_catalog.yaml`,
  `tools/ci/gates/app_catalog_rules.py`, `tools/doc_scripts/check_doc_drift.py`,
  `tools/doc_scripts/generate_doc_indexes.py`,
  [`fire-drill.md`](../topics/disaster-recovery/fire-drill.md) and
  `tools/tests/doc_scripts/test_applypatch_hooks.py` as the model for hook tests.
- **Required checks:** `pre-commit run --all-files`; the new hook behavior with
  a real `git am` in a throwaway repository, and a control that fails without it.

## Risks

- The exemption list is the largest cost and could stall at a few hard apps;
  stage 5 goes by topic group so a stall is visible.
- Records written to satisfy the check rather than to answer the question would
  read as filler; a section that does not apply must say why.

## Open items

- Whether the readiness checklist should block `done` mechanically, or stay a
  template line, is left to stage 4 once stage 2's check exists.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
