---
id: PROJ-cloud-credentials-sdk-followups
title: "Cloud Credential Scripts: Remaining SDK Call Sites"
type: project
status: building
blocked: false
summary: "Move check_freshness.py's OCI key lookup and openbao_utils/audit.py's B2 and OCI listings onto the SDKs ADR 0029 chose."
allowed_paths:
  - tools/cloud_credentials/check_freshness.py
  - tools/cloud_credentials/rotation_keys/oci_scim.py
  - tools/openbao_utils/audit.py
  - tools/tests/cloud_credentials/test_check_freshness.py
  - tools/tests/cloud_credentials/rotation_keys/test_oci_scim.py
  - tools/tests/cloud_credentials/_oci_objects.py
  - tools/tests/cloud_credentials/test_oci_objects.py
  - tools/tests/cloud_credentials/_b2_objects.py
  - tools/tests/cloud_credentials/test_b2_objects.py
  - tools/tests/cloud_credentials/conftest.py
  - tools/tests/_oci_objects.py
  - tools/tests/test_oci_objects.py
  - tools/tests/_b2_objects.py
  - tools/tests/test_b2_objects.py
  - tools/tests/conftest.py
  - tools/tests/openbao_utils/test_audit.py
  - docs/topics/secrets/cloud-credentials/**
  - docs/topics/engineering/conventions.md
---

# Cloud Credential Scripts: Remaining SDK Call Sites

[ADR 0029](../decisions/0029-cloud-provider-api-client-library/revision-000.md) puts OCI SCIM and B2 calls on their official SDKs. Three call sites were left on the providers' HTTP APIs when the rest moved, and this project finishes them. Each is a small, read-only call, but each needs a live check before it merges.

## Scope

- `check_freshness.py`'s OCI key lookup (`session.get(.../CustomerSecretKeys/<id>)`).
- `openbao_utils/audit.py`'s `audit_oci()` (a filtered list through the same raw SCIM session) and `audit_b2()` (a raw `b2_authorize_account` and `b2_list_keys`, with a v2-then-v4 fallback its own comment marks as unverified).
- `rotation_keys/oci_scim.py`'s `oci_scim_session()`, once nothing calls it.

Not in scope, and recorded in [ADR 0029](../decisions/0029-cloud-provider-api-client-library/revision-000.md): R2, OCI's classic-IAM bootstrap, `AppClientSecretRegenerator`, and `check_freshness.py`'s Telegram call.

## Decision

No new decision: this carries out [ADR 0029](../decisions/0029-cloud-provider-api-client-library/revision-000.md), which is `accepted`, for call sites the earlier project did not reach.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | `check_freshness.py`'s OCI lookup → `IdentityDomainsClient.get_customer_secret_key` | In progress | both leaf keys' expiry read through the SDK client against the real tenancy matches the raw call, and `check_freshness.py` no longer imports `oci_scim_session` |
| 2 | `audit.py`'s `audit_b2()` → `b2sdk` (`b2_rotation_api` / `b2_list_keys` already exist), `audit_oci()` → the SDK list call | In progress | a live `audit.py` run reports the same keys and the same ACTIVE/ORPHAN markers as before, and `audit.py` makes no raw B2 or OCI call |
| 3 | Delete `oci_scim_session()` and its tests | Not started | nothing references it |

## Acceptance criteria

- [ ] No raw `requests` call remains in `tools/cloud_credentials` or `tools/openbao_utils` for B2 or OCI SCIM; the exceptions are the ones ADR 0029 records.
- [ ] Mocks for the new call sites are `autospec`'d against the SDK types, and the suite passes.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the rotation and leaf-key flows in `leaf_keys/` and `rotation_keys/` other than `oci_scim.py`.
- **Relevant files and interfaces:** `leaf_keys/oci.py` and `oci_bootstrap.py` already call SCIM through `oci_identity_domains_client()`; `leaf_keys/b2.py` already has `b2_rotation_api()` and `b2_list_keys()`.
- **Required checks:** `pre-commit run --all-files`, plus a live read-only run of each changed script before the PR merges. An SDK attribute mismatch in an earlier stage (`FullApplicationKey` stores its key ID as `id_`, not `application_key_id`) passed static inspection and unit tests and showed up only live.

## Risks

- `oci_bootstrap.py`'s Apps-by-displayName lookup (`_find_app_id`, `list_apps(filter=...)`) shares the client and signer plumbing already proven live but has not been exercised on its own. Low risk, since it is a simple read on the same authenticated client.

## Open items

- `create_leaf_keys.py` and `create_rotation_keys.py` each carry an identical copy of the provider-error mapping (`_PROVIDER_ERRORS` and `_format_provider_error`), translating `b2sdk`, `oci`, and `requests` errors into this repo's print-then-`SystemExit(1)` convention. Whether that becomes one shared helper or stays per entry point is undecided; [ADR 0030](../decisions/0030-openbao-client-implementation-in-repo-python/revision-000.md) settled the same question for `hvac` and `paramiko`, and the two need not match.

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
