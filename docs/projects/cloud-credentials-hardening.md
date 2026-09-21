---
id: PROJ-cloud-credentials-hardening
title: "Cloud Credential Scripts: SDK Adoption + Error-Handling Hardening"
type: project
status: in-progress
summary: "Selective official-SDK adoption (OCI's `identity_domains` client, `b2sdk`) plus error-handling hardening for `tools/cloud_credentials`."
---

# Cloud Credential Scripts: SDK Adoption + Error-Handling Hardening

**Status:** In progress

Replaces `tools/cloud_credentials`'s raw `requests` calls with
official SDKs where one exists and is a clear improvement, and closes
the error-handling gap that review surfaced along the way. Scope and
sequencing are decided in
[ADR 0029](../decisions/0029-cloud-provider-api-client-library/revision-000.md);
this doc tracks build status only. `cache.py`'s OpenBao/SSH client is
[`hvac`/`paramiko`-based](../decisions/0030-openbao-client-implementation-in-repo-python/revision-000.md);
every stage below that reads/writes through `scoped()` already
benefits from that.

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | Fix uncaught `subprocess.TimeoutExpired` in `verify.py`'s rclone retry loop (bug fix, no SDK — `rclone` has no Python bindings) | Done |
| 2 | OCI SCIM leaf/rotation → `oci.identity_domains.IdentityDomainsClient` | Done |
| 3 | B2 leaf/rotation → `b2sdk` | Done |
| 4 | `verify.py`'s `rclone` calls → `boto3` (leaning yes) / `restore_all.py`'s stay on `rclone` (leaning no) | Not started |
| 5 | Re-baseline `tools/tests/cloud_credentials/` mocks for stages 2-4 | Not started |
| 6 | R2 / OCI classic-IAM bootstrap — only if a stage above changes ADR 0029's call | Not started |

## Stage detail

### Stage 1 — `verify.py` timeout fix

Done. `_run_rclone_with_retry` now catches `subprocess.TimeoutExpired`
around the rclone call and folds it into the same non-zero-exit path
via a synthetic `CompletedProcess` — a hang fails like any other
non-retryable error instead of raising out of the retry loop
uncaught.

### Stage 2 — OCI SCIM → `IdentityDomainsClient`

Done. Covers `leaf_keys/oci.py`, `rotation_keys/oci_bootstrap.py`, and
`rotation_keys/oci_scim.py`. `rotation_keys/oci_iam.py`'s classic-IAM
bootstrap is a separate, unrelated auth model and isn't part of this
stage — see Stage 6.

**Confirmed live** — [ADR 0029](../decisions/0029-cloud-provider-api-client-library/revision-000.md)'s
claim that the SDK's model classes reproduce the exact field shape
[0016](../decisions/0016-oci-credential-creation-and-expiry/revision-000.md)
confirmed live against the raw API held: a real create+delete
round-trip through `oci_identity_domains_client()` against the actual
tenancy succeeded, with populated `access_key`/`secret_key` and a
plausible `expires_on` ~90 days out. The Apps-by-displayName lookup
(`oci_bootstrap.py`'s `_find_app_id`) shares the same client/signer
plumbing just proven live but wasn't separately spiked — low residual
risk, since `list_apps(filter=...)` is a simpler read-only call on the
same authenticated client.

**Two findings not in the original draft, both surfaced before the
live spike, by static SDK inspection:**

- `IdentityDomainsClient` has no built-in bearer-token auth mode — its
  `signer` only implements OCI's own API-key Signature V1. The
  implementation adds a `requests.auth.AuthBase` subclass
  (`oci_scim.py`'s `_BearerTokenSigner`) that injects the SCIM OAuth2
  token instead, plus well-formed-but-inert placeholder config values
  to satisfy `IdentityDomainsClient.__init__`'s config validation
  (which runs regardless of which signer is used) — this is exactly
  what the live spike exercised end to end.
- There is no SDK method for `AppClientSecretRegenerator` at all — not
  a subset of the operations, not modeled under a different name.
  `rotation_keys/oci_bootstrap.py`'s `rotate_oci_rotation_key` stays on
  raw `requests` for that one call regardless of how Stage 2 resolves;
  everything else in that module (the Apps-by-displayName lookup) now
  goes through the SDK.

### Stage 3 — B2 → `b2sdk`

Done. Covers `leaf_keys/b2.py`, `rotation_keys/b2.py`, and the B2 call
sites in `check_freshness.py`/`create_snapshot_readonly_keys.py`/
`create_snapshot_write_keys.py`. Implementation lands across all five
files (they share `leaf_keys/b2.py`'s `b2_rotation_api`/
`b2_lookup_bucket_id`/`b2_create_leaf_key`/`b2_delete_key`/`b2_list_keys`,
so a partial swap would leave callers broken); tests updated to mock
`b2sdk.v2.B2Api` instead of raw `requests` calls.

**Confirmed live, after one real bug caught along the way.**
[ADR 0029](../decisions/0029-cloud-provider-api-client-library/revision-000.md)'s
claim that `b2sdk` exposes the precise capability list without
abstracting it away held —
`B2Api.create_key(capabilities: list[str], ...)` takes the raw
capability strings directly and a live create returned them back
unwrapped on `.capabilities`, exactly matching what was requested. But
the first live spike attempt failed with `AttributeError:
'FullApplicationKey' object has no attribute 'application_key_id'`:
`FullApplicationKey.__init__` takes `application_key_id` as a
constructor parameter but stores it as `self.id_`, not
`self.application_key_id` — a mismatch static inspection (checking the
constructor signature, not what it actually assigns) missed entirely.
Fixed across every call site (`leaf_keys/b2.py`, `rotation_keys/b2.py`,
`create_snapshot_readonly_keys.py`, `create_snapshot_write_keys.py`); a
second live spike with the corrected attribute confirmed create,
capability match, and delete all succeeding.

The unit tests didn't catch the attribute bug either, for a related
reason: they mocked the return value as a bare
`MagicMock(application_key_id=...)`, which accepts any attribute name
silently. Every such mock now uses `MagicMock(spec=FullApplicationKey,
id_=..., ...)` instead — confirmed, by deliberately reintroducing the
bug, that this now fails the unit tests too, not just a live run.

### Stage 4 — `verify.py` → boto3

Scoped in
[`rclone-boto3-scope-not-blanket-swap.md`](../decisions/drafts/rclone-boto3-scope-not-blanket-swap.md) —
explicitly does not extend to `cloud_sync`, `snapshot-push.sh.j2`, or
`check-freshness.sh.j2` (bash/containerized, and `cloud_sync`'s
`rclone copy` is load-bearing for
[ADR 0010](../decisions/0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md)). Blocked on
that draft's Assumptions, in particular confirming `verify.py`'s
credential already lives as a Python value before this swap, so the
credentials-in-process trade `restore_all.py` avoids doesn't newly
apply here. `boto3` is not already a `pyproject.toml` dependency from
[`ansible-collections-audit.md`](ansible-collections-audit.md)'s
Stage 1 (`amazon.aws.s3_bucket`) — that stage confirmed live it only
needs `boto3` on the Ansible target host (`storage`, via `apt`), not
the controller, so this would be the first stage to actually add it to
`pyproject.toml`, not a second entry to reconcile with an existing one.

## Open items

- Whether a shared retry/exception-mapping helper (translating
  `b2sdk`/`oci` errors into this repo's existing
  `print`-then-`SystemExit(1)`-with-guidance convention) gets built
  once alongside Stage 2, or left ad hoc per module — not decided yet.
  A parallel question existed for `hvac`/`paramiko` errors, settled by
  [ADR 0030](../decisions/0030-openbao-client-implementation-in-repo-python/revision-000.md); the
  two aren't required to reach the same answer.
- `openbao_utils/audit.py`'s `audit_b2()`/`audit_oci()` still call B2/OCI's
  raw APIs directly (`requests`, not `b2sdk`/`oci.identity_domains`),
  untouched by Stages 2-3 above — moved here from
  `openbao-python-client-hardening.md`'s own open items before that
  project closed. Whether this file adopts the same SDKs, and on what
  schedule, is this project's call, not an independent one.
- `check_freshness.py`'s single Telegram `sendMessage` call has no SDK
  candidate worth adding for one endpoint — out of scope, noted here so
  it isn't re-proposed later. `verify.py`'s `rclone` call itself may or
  may not survive Stage 4 (see that stage's linked draft); its
  uncaught-timeout bug is fixed regardless, as Stage 1.
- `cloud_sync`'s bulk-copy job, `snapshot-push.sh.j2`, and
  `check-freshness.sh.j2` are explicitly out of scope for any boto3
  swap — bash/containerized, and `cloud_sync`'s `rclone copy` is
  load-bearing for ADR 0010. See
  [`rclone-boto3-scope-not-blanket-swap.md`](../decisions/drafts/rclone-boto3-scope-not-blanket-swap.md)
  so this isn't re-raised without context.
- Whether those same three bash scripts get rewritten as Python
  wrappers around the same `rclone` binary (better error handling and
  library support, zero change to ADR 0010's security semantics since
  the binary invoked doesn't change) is a live, separate question —
  see that draft's "wrapper language" section. Not yet its own stage;
  needs a deployment-shape spike first (adding a Python interpreter to
  the pinned `rclone/rclone` image or building a new one).

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes) — run
before deleting this doc once every stage is Done.

- [ ] Every `Done` stage's rationale exists as a real ADR, or plainly
      didn't need one.
- [ ] Every `Done` stage's current behavior is in a topic doc.
- [ ] Every open item is resolved-and-promoted or moved to where it
      belongs next.
- [ ] Every cross-reference into this doc elsewhere in the repo is
      updated or removed.
