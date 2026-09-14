# Cloud Credential Scripts: SDK Adoption + Error-Handling Hardening

**Status:** Not started

Replaces `ansible/cloud_credentials`'s raw `requests` calls with
official SDKs where one exists and is a clear improvement, and closes
the error-handling gap that review surfaced along the way. Scope and
sequencing are decided in
[`cloud-credentials-selective-sdk-adoption-not-blanket-swap.md`](../decisions/drafts/cloud-credentials-selective-sdk-adoption-not-blanket-swap.md);
this doc tracks build status only. `cache.py`'s OpenBao/SSH client is
tracked separately in
[`openbao-python-client-hardening.md`](openbao-python-client-hardening.md) —
every stage below that reads/writes through `scoped()` benefits once
that project's Stage 1 lands, but none of them are blocked on it (raw
`requests` still works meanwhile).

## Stages

| # | Stage | Status |
| :-: | :--- | :--- |
| 1 | Fix uncaught `subprocess.TimeoutExpired` in `verify.py`'s rclone retry loop (bug fix, no SDK — `rclone` has no Python bindings) | Not started |
| 2 | OCI SCIM leaf/rotation → `oci.identity_domains.IdentityDomainsClient` | Not started |
| 3 | B2 leaf/rotation → `b2sdk` | Not started |
| 4 | `verify.py`'s `rclone` calls → `boto3` (leaning yes) / `restore_all.py`'s stay on `rclone` (leaning no) | Not started |
| 5 | Re-baseline `ansible/tests/cloud_credentials/` mocks for stages 2-4 | Not started |
| 6 | R2 / OCI classic-IAM bootstrap — only if a stage above changes the draft's call | Not started |

## Stage detail

### Stage 1 — `verify.py` timeout fix

Independent of every other stage and the decision draft's options —
catch `subprocess.TimeoutExpired` around the rclone call in
`_run_rclone_with_retry` and route it through the same
transient-failure path a non-zero exit already takes. No blocking
Assumption; can land on its own at any point.

### Stage 2 — OCI SCIM → `IdentityDomainsClient`

Covers `leaf_keys/oci.py`, `rotation_keys/oci_bootstrap.py`, and
`rotation_keys/oci_scim.py`. Blocked on the decision draft's first
Assumption — a spike confirming the SDK's model classes reproduce the
exact field shape (`user.ocid`, `expiresOn` immutability, populated
`accessKey`/`secretKey` on create)
[0016](../decisions/0016-oci-expiry-via-scim-not-self-tracked-cache-files.md)
confirmed live against the raw API. `rotation_keys/oci_iam.py`'s
classic-IAM bootstrap is a separate, unrelated auth model and isn't
part of this stage — see Stage 6.

### Stage 3 — B2 → `b2sdk`

Covers `leaf_keys/b2.py`, `rotation_keys/b2.py`, and the B2 call sites
in `check_freshness.py`/`create_snapshot_readonly_keys.py`/
`create_snapshot_write_keys.py`. Blocked on the decision draft's second
Assumption — confirming `b2sdk` exposes the precise capability list
(bucket-restriction rejection, `listAllBucketNames`, `readFiles`) this
repo's key-scoping depends on, rather than abstracting it away.

### Stage 4 — `verify.py` → boto3

Scoped in
[`rclone-boto3-scope-not-blanket-swap.md`](../decisions/drafts/rclone-boto3-scope-not-blanket-swap.md) —
explicitly does not extend to `cloud_sync`, `snapshot-push.sh.j2`, or
`check-freshness.sh.j2` (bash/containerized, and `cloud_sync`'s
`rclone copy` is load-bearing for
[ADR 0010](../decisions/0010-cloud-sync-copy-not-sync.md)). Blocked on
that draft's Assumptions, in particular confirming `verify.py`'s
credential already lives as a Python value before this swap, so the
credentials-in-process trade `restore_all.py` avoids doesn't newly
apply here.

## Open items

- Whether Option B (selective adoption) holds, or a stage's spike
  pushes toward Option A/C instead — see the decision draft's
  Assumptions; each one names its own check.
- Whether a shared retry/exception-mapping helper (translating
  `b2sdk`/`oci` errors into this repo's existing
  `print`-then-`SystemExit(1)`-with-guidance convention) gets built
  once alongside Stage 2, or left ad hoc per module — not decided yet.
  A parallel question exists for `hvac`/`paramiko` errors in
  [`openbao-python-client-hardening.md`](openbao-python-client-hardening.md);
  the two aren't required to reach the same answer.
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
