"""Backblaze B2 leaf-key create/rotate logic, via b2sdk (Stage 3,
docs/projects/cloud-credentials-hardening.md) - not raw requests calls
against B2's HTTP API directly.
"""

from __future__ import annotations

import sys

from b2sdk.v2 import B2Api, InMemoryAccountInfo
from b2sdk.v2.exception import B2Error, NonExistentBucket

from cloud_credentials.cache import scoped
from cloud_credentials.expiry import QUARTERLY_SECONDS
from cloud_credentials.verify import verify_leaf_via_rclone

cached, read_cache, write_cache, require_cache_file = scoped("leaf")
# b2_rotation_api() below reads the rotation-tier session credential
# rotation_keys/b2.py writes - a second, differently-scoped binding,
# since this module's own leaf keys and that session live under
# different top-level Vault paths (ADR 0020).
_, _, _, _rotation_require_cache_file = scoped("rotation")

B2_BUCKET = "homelab-backups-b2"


# writeFiles without deleteFiles — deleteFiles is the one capability
# genuinely excluded from either key; everything else here is required
# for rclone to function at all, not a privilege choice.
#
# listAllBucketNames is required here, confirmed live and by
# Backblaze's own docs (three separate pages state it) plus a real
# rclone issue (rclone/rclone#5020) with this exact symptom: a
# bucket-restricted key without it gets a blanket 403 on the
# S3-compatible API, even for operations its other capabilities should
# allow. listBuckets alone isn't enough for S3-compat access to a
# bucket-restricted key — unrelated to file-level capabilities, applies
# regardless of read/write/delete scope.
#
# readFiles is required on the write leaf too, confirmed live. rclone's
# S3 backend calls HeadObject on the destination before every copy,
# fresh object or not, to decide skip-vs-upload — B2 maps HeadObject to
# readFiles, not listFiles. A write leaf without readFiles fails
# outright on every copy attempt, not just on already-existing objects.
B2_LEAF_CAPABILITIES = {
    "write": ["listBuckets", "listAllBucketNames", "listFiles", "readFiles", "writeFiles"],
    "read": ["listBuckets", "listAllBucketNames", "listFiles", "readFiles"],
}


def b2_rotation_api() -> B2Api:
    """A B2Api authorized with the cached rotation key - InMemoryAccountInfo,
    not SqliteAccountInfo, since nothing here runs long enough to
    benefit from b2sdk's own on-disk auth cache and this repo already
    has its own cache (Vault, via cache.py)."""
    rotation_key_id = _rotation_require_cache_file(
        "_rotation-key-backblaze-b2-key-id",
        "Run: python3 -m cloud_credentials.create_rotation_keys --provider b2",
    )
    rotation_key = _rotation_require_cache_file(
        "_rotation-key-backblaze-b2-application-key",
        "Run: python3 -m cloud_credentials.create_rotation_keys --provider b2",
    )
    api = B2Api(InMemoryAccountInfo())
    api.authorize_account("production", rotation_key_id, rotation_key)
    return api


def b2_lookup_bucket_id(api: B2Api, bucket_name: str = B2_BUCKET) -> str:
    # bucket_name defaults to cloud_sync's own B2_BUCKET so every
    # existing call site is unaffected — create_snapshot_readonly_keys.py
    # is the one caller that passes a different bucket.
    try:
        return api.get_bucket_by_name(bucket_name).id_
    except NonExistentBucket:
        print(f"b2: bucket {bucket_name!r} doesn't exist yet — create it first", file=sys.stderr)
        sys.exit(1)


def b2_create_leaf_key(api: B2Api, bucket_id: str, leaf: str):
    # Returns a FullApplicationKey - read its key id back via .id_, not
    # .application_key_id, despite that being the constructor's own
    # parameter name (confirmed live; see ADR 0029).
    return api.create_key(
        capabilities=B2_LEAF_CAPABILITIES[leaf],
        key_name=f"homelab-cloud-sync-{leaf}",
        bucket_id=bucket_id,
        valid_duration_seconds=QUARTERLY_SECONDS,
    )


def b2_delete_key(api: B2Api, application_key_id: str) -> None:
    api.session.delete_key(application_key_id)


def b2_list_keys(api: B2Api):
    """Every key on the account, native `expiration_timestamp_millis`
    included when the key was created with valid_duration_seconds.
    Used by check_freshness.py instead of self-tracking B2's expiry -
    B2 already reports it, no separate cache file needed."""
    return list(api.list_keys())


def create_b2() -> None:
    write_done = cached("backblaze-b2-write-access-key") and cached("backblaze-b2-write-secret-key")
    read_done = cached("backblaze-b2-read-access-key") and cached("backblaze-b2-read-secret-key")
    if write_done and read_done:
        print("b2: both credentials already cached, skipping")
        return

    api = b2_rotation_api()
    bucket_id = b2_lookup_bucket_id(api)

    for leaf, done in [("write", write_done), ("read", read_done)]:
        if done:
            continue
        key = b2_create_leaf_key(api, bucket_id, leaf)
        write_cache(f"backblaze-b2-{leaf}-access-key", key.id_)
        write_cache(f"backblaze-b2-{leaf}-secret-key", key.application_key)
        print(f"b2 {leaf}: cached")


def rotate_b2(leaves: list[str]) -> bool:
    api = b2_rotation_api()
    bucket_id = b2_lookup_bucket_id(api)
    region = require_cache_file("backblaze-b2-region", "Set via bootstrap.py / secrets_registry.yaml — same value storage.yaml's rclone.conf uses.")
    endpoint = f"https://s3.{region}.backblazeb2.com"

    all_ok = True
    for leaf in leaves:
        old_key_id = read_cache(f"backblaze-b2-{leaf}-access-key")

        new_key = b2_create_leaf_key(api, bucket_id, leaf)
        new_access_key, new_secret_key = new_key.id_, new_key.application_key

        ok, detail = verify_leaf_via_rclone(new_access_key, new_secret_key, endpoint, region, B2_BUCKET, leaf)
        if not ok:
            print(
                f"b2 {leaf}: new key {new_access_key} failed verification ({detail}). "
                f"Old key {old_key_id or '(none cached)'} left untouched and still in use; "
                f"new key left live but NOT cached or revoked — investigate, then either "
                f"retry or revoke {new_access_key} by hand in the B2 Console.",
                file=sys.stderr,
            )
            all_ok = False
            continue

        write_cache(f"backblaze-b2-{leaf}-access-key", new_access_key)
        write_cache(f"backblaze-b2-{leaf}-secret-key", new_secret_key)

        if old_key_id:
            try:
                b2_delete_key(api, old_key_id)
                print(f"b2 {leaf}: old key {old_key_id} revoked")
            except B2Error as exc:
                print(
                    f"b2 {leaf}: new key cached, but revoking old key {old_key_id} failed ({exc}) — revoke it by hand in the B2 Console.",
                    file=sys.stderr,
                )

        print(f"b2 {leaf}: rotated and verified")

    return all_ok
