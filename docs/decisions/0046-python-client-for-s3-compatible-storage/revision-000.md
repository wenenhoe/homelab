---
id: ADR-0046
revision: 0
type: adr
title: Python client for S3-compatible object storage
solution: rclone for every S3-compatible call, Python and bash alike; boto3 is not adopted
summary: Which client Python code uses to talk to S3-compatible storage, and where rclone stays.
topic: cloud-credentials
status: approved
related: [ADR-0010, ADR-0029]
---

# 0046. Keep rclone as the one S3-compatible client

## Problem

Python code in this repo exercises S3-compatible storage (B2, R2, OCI, SeaweedFS). It needs one client whose behavior against each provider is known, without weakening the guarantees the backup design rests on.

## Context

`rclone` appears at five call sites, in two shapes:

- **Bash, containerized, bulk copy:** `cloud_sync`'s `run.sh.j2` (`rclone copy seaweedfs:<bucket>/<path> <target>:<bucket>/<path>` per job in `/jobs.txt`), `openbao_backup`'s `snapshot-push.sh.j2`, and `backup_agent`'s `check-freshness.sh.j2`. All are POSIX `sh` running `rclone` inside a pinned `rclone/rclone` container via `docker run`.
- **Python, single object:** `cloud_credentials/verify.py` (`lsjson` and `copyto` against a small marker object) and `restore_all.py` (`rclone_lsjson`/`copyto`, one `lsjson` per discovery attempt and one `copyto` per restored app). Both shell out via `subprocess`.

**The bulk-copy sites are not a candidate for another client.** `cloud_sync`'s `rclone copy` is the control [ADR 0010](../0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md) documents: a compromised on-prem host can't touch the offsite copy because `copy` never overwrites or deletes, not from IAM scoping alone. Reimplementing that with hand-written client calls means re-deriving and re-proving the property.

**What `verify.py` is for.** `verify_leaf_via_rclone` proves that a freshly minted leaf key works over the path production uses, before the old key is revoked. The write leaf's need for `readFiles` on B2 is an example of what that catches: rclone sends a HEAD before every copy, and a check that sends no HEAD never exercises that permission.

**Credential handling is not what separates the options.** `restore_all.py` never holds S3 credentials in its own process. `verify.py` already does: `rotate_*` and the snapshot key scripts mint the key as a Python value and pass it to `verify_leaf_via_rclone`, which writes it to a single-use `rclone.conf` (mode 0600) in a temporary directory.

**Measured against B2, R2, and OCI** with rclone 1.75.0 and boto3 1.43.108, using freshly minted leaf keys:

- **Request sequences differ.** rclone lists with the v1 `ListObjects` call (no `list-type=2`) on all three providers. For a write it sends HEAD, PUT, HEAD. boto3's `list_objects_v2` and `put_object` send a listing v2 call and a single PUT.
- **boto3 needs different settings per provider.**
  - OCI answers boto3's default-checksum PUT with `501 NotImplemented`; `request_checksum_calculation="when_required"` works, with or without a HEAD first.
  - B2 closes the connection without an HTTP response on boto3's PUT when it carries `Expect: 100-continue` under `when_required`. With `Expect` removed, `when_required` gets `400 InvalidRequest`. Of the variants tried, only the default checksum mode (`aws-chunked` with a trailing CRC32) with `Expect` removed succeeded. The default mode with `Expect` present was not tried.
  - R2 accepts every variant tried.
- **Retrying is controllable.** With `retries={"total_max_attempts": 1}`, boto3 made one HTTP request per call and surfaced 401 (R2) or 403 `SignatureDoesNotMatch` (OCI) as `ClientError`, so a caller can own the retry loop and gate it on HTTP status.

## Decision

`rclone` remains the S3-compatible client at every call site, Python and bash. `verify.py` and `restore_all.py` stay on it, and `boto3` is not added to `pyproject.toml`.

Two reasons decide it:

1. **Verification must follow production's client.** boto3 sends a different sequence than rclone does (no HEAD, a different listing call), so a key could pass a boto3 check and still fail under rclone. Reproducing rclone's sequence by hand re-implements what rclone already does.
2. **One client config instead of one per provider.** rclone needs one configuration for all three providers, whose requirements (`no_check_bucket`, explicit `region`, endpoint scheme) are recorded once in [`rotation.md`](../../topics/secrets/cloud-credentials/rotation.md). boto3 would add a per-provider checksum setting and, for B2, a hook that removes a header botocore adds by default.

What the swap would remove is small: one `subprocess` call and a short-lived `rclone.conf` in a temporary directory.

## Alternatives considered

- **boto3 for both Python sites.** Gives up `restore_all.py`'s property that S3 credentials never enter the Python process, and carries the per-provider settings above.
- **boto3 for `verify.py` only.** Gives up nothing on credential handling (the key is already a Python value there), but loses the same-path property and still needs the per-provider settings.
- **Third-party rclone wrappers** (`rclone_python`, `py-rclone`). They shell out to the same CLI, so they remove no wire-format drift, and they are a single maintainer's project in a credential-verification path.
- **rclone's Remote Control API.** Needs a standing daemon and an auth token for scripts that run a few times per quarter.

## Consequences

- `cloud_sync`, `snapshot-push.sh.j2`, and `check-freshness.sh.j2` stay on `rclone` regardless of future client choices. Re-raising boto3 for them should point back here.
- Swapping rclone for boto3 plus `hvac` would not remove a secret from disk, only change which one: `rclone.conf` holds real access and secret keys today, and a boto3 path needs its own long-lived OpenBao credential unless it fetches one every run. That is the same problem one level up as [ADR 0047](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md), not something this record resolves.
- `verify.py` keeps its status-string retry gate (`StatusCode: 401`/`403` in rclone's stderr) and its timeout handling.
- Behavior is described in [`rotation.md`](../../topics/secrets/cloud-credentials/rotation.md) and [`scoping.md`](../../topics/secrets/cloud-credentials/scoping.md).

## Non-goals

Whether the three bash scripts become Python wrappers around the same `rclone` binary is a separate question. Doing so would keep `rclone copy`'s ADR 0010 semantics unchanged, but it changes the deployment shape (a container with no Python interpreter today), so it needs its own record and a spike on adding an interpreter to the pinned image or building a thin wrapper image.

## Reconsideration triggers

- `cloud_sync` or `restore_all.py` stops using rclone, so verification should follow the new client.
- A provider's S3-compatible API starts requiring a request shape rclone cannot produce.
