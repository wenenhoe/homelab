"""Backblaze B2 leaf-key create/rotate logic."""

from __future__ import annotations

import sys

import requests

from cloud_credentials.cache import cached, read_cache, require_cache_file, write_cache
from cloud_credentials.verify import verify_leaf_via_rclone

B2_BUCKET = "homelab-backups-b2"

B2_AUTHORIZE_URL = "https://api.backblazeb2.com/b2api/v2/b2_authorize_account"


def b2_authorize(key_id: str, key: str) -> dict:
    resp = requests.get(B2_AUTHORIZE_URL, auth=(key_id, key), timeout=45)
    resp.raise_for_status()
    return resp.json()


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


def b2_lookup_bucket_id(session, api_url: str, account_id: str) -> str:
    bucket_resp = session.post(
        f"{api_url}/b2api/v2/b2_list_buckets",
        json={"accountId": account_id, "bucketName": B2_BUCKET},
    )
    bucket_resp.raise_for_status()
    buckets = bucket_resp.json()["buckets"]
    if not buckets:
        print(f"b2: bucket {B2_BUCKET!r} doesn't exist yet — create it first", file=sys.stderr)
        sys.exit(1)
    return buckets[0]["bucketId"]


def b2_create_leaf_key(session, api_url: str, account_id: str, bucket_id: str, leaf: str) -> dict:
    resp = session.post(
        f"{api_url}/b2api/v2/b2_create_key",
        json={
            "accountId": account_id,
            "capabilities": B2_LEAF_CAPABILITIES[leaf],
            "keyName": f"homelab-cloud-sync-{leaf}",
            "bucketId": bucket_id,
        },
    )
    resp.raise_for_status()
    return resp.json()


def b2_delete_key(session, api_url: str, application_key_id: str) -> None:
    session.post(f"{api_url}/b2api/v2/b2_delete_key", json={"applicationKeyId": application_key_id}).raise_for_status()


def b2_rotation_session() -> tuple[requests.Session, str, str]:
    rotation_key_id = require_cache_file(
        "_rotation-key-backblaze-b2-key-id",
        "Run: python3 -m cloud_credentials.create_rotation_keys --provider b2",
    )
    rotation_key = require_cache_file(
        "_rotation-key-backblaze-b2-application-key",
        "Run: python3 -m cloud_credentials.create_rotation_keys --provider b2",
    )
    auth = b2_authorize(rotation_key_id, rotation_key)
    session = requests.Session()
    session.headers["Authorization"] = auth["authorizationToken"]
    return session, auth["accountId"], auth["apiUrl"]


def create_b2() -> None:
    write_done = cached("backblaze-b2-write-access-key") and cached("backblaze-b2-write-secret-key")
    read_done = cached("backblaze-b2-read-access-key") and cached("backblaze-b2-read-secret-key")
    if write_done and read_done:
        print("b2: both credentials already cached, skipping")
        return

    session, account_id, api_url = b2_rotation_session()
    bucket_id = b2_lookup_bucket_id(session, api_url, account_id)

    for leaf, done in [("write", write_done), ("read", read_done)]:
        if done:
            continue
        body = b2_create_leaf_key(session, api_url, account_id, bucket_id, leaf)
        write_cache(f"backblaze-b2-{leaf}-access-key", body["applicationKeyId"])
        write_cache(f"backblaze-b2-{leaf}-secret-key", body["applicationKey"])
        print(f"b2 {leaf}: cached")


def rotate_b2(leaves: list[str]) -> bool:
    session, account_id, api_url = b2_rotation_session()
    bucket_id = b2_lookup_bucket_id(session, api_url, account_id)
    region = require_cache_file("backblaze-b2-region", "Set via bootstrap_secrets.py / secrets_registry.yaml — same value storage.yaml's rclone.conf uses.")
    endpoint = f"https://s3.{region}.backblazeb2.com"

    all_ok = True
    for leaf in leaves:
        old_key_id = read_cache(f"backblaze-b2-{leaf}-access-key")

        new_body = b2_create_leaf_key(session, api_url, account_id, bucket_id, leaf)
        new_access_key, new_secret_key = new_body["applicationKeyId"], new_body["applicationKey"]

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

        if old_key_id:
            try:
                b2_delete_key(session, api_url, old_key_id)
                print(f"b2 {leaf}: old key {old_key_id} revoked")
            except requests.HTTPError as exc:
                print(
                    f"b2 {leaf}: new key verified and will be cached, but revoking old key {old_key_id} failed ({exc}) — revoke it by hand in the B2 Console.",
                    file=sys.stderr,
                )

        write_cache(f"backblaze-b2-{leaf}-access-key", new_access_key)
        write_cache(f"backblaze-b2-{leaf}-secret-key", new_secret_key)
        print(f"b2 {leaf}: rotated and verified")

    return all_ok
