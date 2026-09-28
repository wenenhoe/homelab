---
id: PROJ-secret-catalog
title: "Secret Catalog"
type: project
status: not-started
blocked: false
summary: "One loader and validator for secret definitions, explicit source/store/scope fields, and secrets_registry renamed secret_catalog."
decision: ADR-0066/0
---

# Secret Catalog

Makes each secret definition state how its value is produced and where it
is kept, and gives every tool one loader and one validator instead of five
loaders and a convention. Staged so the validator lands before the schema
it will check changes, and the mechanical rename comes last.

## Scope

`secrets_registry.yaml`'s schema, its loaders and readers under `tools/`,
the `secrets` role and `rotate-secret.yaml`, the deploy-ordering CI
fixture, and the `secrets_registry` → `secret_catalog` rename. Not in
scope: secret values, generation, rotation policy, and the OpenBao path
layout.

## Decision

Implements
[ADR 0066](../decisions/0066-how-a-secret-definition-states-production-and-storage/revision-000.md),
still `working`, so this project stays `not-started` until that
revision's assumptions are resolved.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Shared loader and validator for the current schema | Not started | The four `tools/openbao_utils/` modules and the CI fixture load the registry through one function; a validator enforcing the header's rules runs in pre-commit and CI against the real file; no entry changes |
| 2 | `source`/`store`/`scope` schema | Not started | Every entry uses the new fields; every entry's OpenBao path is identical before and after; the `secrets` role, `rotate-secret.yaml`, the tools and the deploy-ordering fixture read `store` instead of the presence of `vault_scope`; Molecule and CI pass |
| 3 | Rename to `secret_catalog` | Not started | The variable, file and every reference use the new name, including docs and Molecule scenarios |

Stage status is `Not started`, `In progress`, or `Done`. Stage 2 spans
Ansible and Python in one pull request, since both read the fields.

## Acceptance criteria

- [ ] No tool infers where a secret lives from anything but its `store`.
- [ ] The validator fails on each rule violation, with a unit test per rule.
- [ ] A recorded diff shows every entry's OpenBao path unchanged.
- [ ] The `secrets` role's Molecule scenarios and the deploy-ordering job
      pass on the converted catalog.

## Risks

- The `secrets` role has seven Molecule scenarios with inline registries
  in their `converge.yml`. Stage 2 has to convert each one, which makes
  it the largest pull request here.
- `secrets_registry` appears in 64 files; stage 3 can conflict with
  concurrent work.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or named by a successor project.
- [ ] The linked revision is `accepted`, another project still names it, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
