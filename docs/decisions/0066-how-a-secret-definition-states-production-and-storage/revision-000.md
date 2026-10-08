---
id: ADR-0066
revision: 0
type: adr
title: "How a secret definition states production and storage"
short: Secret definitions
solution: "Flat source, store and scope fields, read through one loader and checked by one validator"
summary: "How a secret's definition says how its value is produced and where it is kept, so no tool has to infer either."
topic: secrets-store
status: accepted
related: [ADR-0013, ADR-0021, ADR-0031, ADR-0064]
---

# 0066. How a secret definition states production and storage

## Problem

A secret's definition has to say how its value comes into being and where
it is kept. Each tool that handles secrets (the `secrets` role, the
OpenBao bootstrap, dump, restore and audit tools, the CI fixtures) has to
read those answers from the definition. None of them should infer them
from something else.

## Context

- Each entry in `secrets_registry.yaml` carries `format` (`hex`, `uuid4` or
  `manual`), which says how the value is produced. Where it is stored is
  implied by whether `vault_scope` is present: present means OpenBao at
  `<scope>/<name>`, absent means the controller-side file cache.
- All 60 current entries fit that reading. 57 have a `vault_scope`. The 3
  that do not are `main-domain` and the two controller AppRole files, and
  the registry header explains why each must stay off OpenBao: Vault access
  itself depends on them.
- The absence-means-file-cache reading is re-derived separately in
  `tools/openbao_utils/` (`bootstrap.py`, `dump.py`, `restore.py`,
  `audit.py`), in `roles/secrets/tasks/` (`main.yaml`, `ensure_secret.yaml`,
  `process_vault_secrets.yaml`), and in `playbooks/rotate-secret.yaml`. The
  CI fixture that emulates the file cache does it by deleting
  `vault_scope` from every entry (`tools/ci/fixtures/strip_vault_scope.py`).
- The rules the entries follow are written as a comment of about 70 lines at the top
  of the registry, not checked by anything before a deploy. `rotate-secret`
  asserts that a generated secret has a scope only when someone rotates it.
- Four modules under `tools/openbao_utils/` each load the registry with
  their own `yaml.safe_load(...)["secrets_registry"]`, and
  `tools/ci/fixtures/secrets_registry.py` is a fifth loader.
- Converting all 60 entries to the fields below leaves every OpenBao path
  as it is today: 57 distinct `<scope>/<n>` paths under the same mount,
  and no entry that has a scope without being stored in OpenBao or the
  reverse. The current file breaks none of the rules below, and has no
  duplicate keys.
- The deploy-ordering CI job needs only the entries on the controller
  file cache. It resolves `main-domain` from the cache, and with nothing
  stored in OpenBao it skips the OpenBao login. With a registry holding
  just the three `controller_file` entries, its `deploy` and `restore`
  runs both pass, and with `main-domain` removed the `restore` run fails
  with the ansible_host resolution verdict, so the check still catches the
  regression it exists for.

## Decision

- The registry is renamed `secret_catalog` (variable and file). "Catalog"
  matches `app_catalog` in [ADR 0065 (App defaults merge)](../0065-where-app-defaults-and-host-intent-are-merged/revision-000.md)
  for the same kind of data: read-only definitions keyed by name.
- Each entry states its production and storage with flat fields:

  ```yaml
  shlink-api-key:
    source: uuid4          # hex | uuid4 | manual   (was `format`)
    store: openbao         # openbao | controller_file
    scope: hosts/services  # was `vault_scope`
  ```

- Rules, all checked:
  - `source: hex` requires `length`; other sources forbid it.
  - `store: openbao` requires `scope`; `controller_file` forbids it.
  - `hex` and `uuid4` require `store: openbao`. Ansible can only generate
    into OpenBao.
  - `manual` requires `description`. `allow_blank` and `sensitive` are
    valid only on `manual`.
- Every reader gets the catalog from one loader under `tools/`, per
  [ADR 0064 (CI and doc check code)](../0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md),
  and a validator that runs in pre-commit and CI enforces the rules. Ansible
  reads the variable directly.
- `store` is stated on every entry. It has no default, so the three
  file-cache entries are visible as exceptions instead of an absence.
- The deploy-ordering CI job's registry override holds only the catalog's
  `store: controller_file` entries, selected through the shared loader
  instead of rewriting every entry. The pre-seed fixture writes dummy
  files for those same entries. The override is not a catalog, so the
  validator does not run on it.

## Alternatives considered

- **Nested `generation:` and `storage:` blocks.** Groups the same three
  facts under two keys. It adds indentation to every entry and gives the
  validator nothing the flat form does not.
- **Keep the `vault_scope` presence convention and only add validation.**
  Enforces the rules but leaves each of the readers above encoding the
  convention. A future third store would touch all of them again.
- **Default `store` to `openbao`.** Shorter entries, but the three
  exceptions become the only entries that say anything, and a typo in
  `store` silently falls back to the default.

## Consequences

- A definition reads as a statement of fact, and a wrong combination fails
  in pre-commit, not at deploy or rotation time.
- The schema change spans Ansible and Python in one pull request, because
  both read the fields. The rename is a separate mechanical change after it:
  `secrets_registry` appears in 64 files.
- `docs/topics/secrets/secrets.md` and the other docs that name the fields change in the
  pull requests that change them.

## Invariants

- No tool decides where a secret lives by anything other than its `store`.
- The catalog's shape is checked before it is deployed.
- An entry's OpenBao path does not change unless a decision says so.

## Non-goals

- Secret values, generation algorithms, or rotation policy.
- The OpenBao path layout, which
  [ADR 0021 (Ownerless secret paths)](../0021-secret-path-layout-for-secrets-with-no-host-owner/revision-000.md)
  covers.
- Adding a store other than `openbao` and `controller_file`.

## Validation

The validator runs against the real catalog in pre-commit and CI, with unit
tests for each rule.
