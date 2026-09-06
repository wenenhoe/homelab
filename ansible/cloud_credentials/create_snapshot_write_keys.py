#!/usr/bin/env python3
"""Mint the standing write-leaf credential Track A stage 2's backup job
uses to push encrypted raft snapshots to R2/B2 — a separate credential
from create_snapshot_readonly_keys.py's break-glass restore key, and
deliberately not the same shape:

- This one is cached to ansible/files/secrets/, like every other leaf
  in create_leaf_keys.py, since it's a routine, standing credential a
  script reads on every backup run — not a one-time value copied into
  the break-glass password-manager entry.
- It carries the same quarterly native expiry every other leaf gets
  (see docs/cloud-credential-creation.md), rotated by hand via
  --rotate the same way create_leaf_keys.py's leaves are, since it's
  now part of the ordinary rotation cycle rather than a dormant
  disaster-recovery credential.
- It's write-only, no delete (B2_LEAF_CAPABILITIES["write"] already
  excludes deleteFiles; R2's permission group is item-level write, not
  admin) — the same no-delete shape cloud_sync's own write leaves use.
  ADR 0006 is why that matters: on R2, where the capability itself
  can't be scoped away, the actual protection is that the backup
  script only ever calls rclone copy, never sync/delete — see that
  script for the invocation.

Scoped to the same openbao-snapshots bucket create_snapshot_readonly_keys.py
targets on both providers — see that script for why a dedicated bucket
(not homelab-backups/-b2) and why both R2 and B2.

Usage (run from ansible/):
    python3 -m cloud_credentials.create_snapshot_write_keys [--provider {r2,b2,all}]
    python3 -m cloud_credentials.create_snapshot_write_keys --provider {r2,b2} --rotate
"""

from __future__ import annotations

import argparse
import hashlib
import sys

import requests

from cloud_credentials.cache import SECRETS_DIR, cached, read_cache, require_cache_file, write_cache
from cloud_credentials.create_snapshot_readonly_keys import SNAPSHOT_BUCKET_B2, SNAPSHOT_BUCKET_R2
from cloud_credentials.expiry import QUARTERLY_SECONDS
from cloud_credentials.leaf_keys.b2 import B2_LEAF_CAPABILITIES, b2_lookup_bucket_id, b2_rotation_session
from cloud_credentials.leaf_keys.r2 import r2_create_leaf_token, r2_delete_token, r2_permission_group_ids, r2_rotation_token
from cloud_credentials.verify import verify_leaf_via_rclone

CACHE_R2_ACCESS = "cloudflare-r2-openbao-snapshot-write-access-key"
CACHE_R2_SECRET = "cloudflare-r2-openbao-snapshot-write-secret-key"  # noqa: S105 - cache filename, not secret value
CACHE_B2_ACCESS = "backblaze-b2-openbao-snapshot-write-access-key"
CACHE_B2_SECRET = "backblaze-b2-openbao-snapshot-write-secret-key"  # noqa: S105 - cache filename, not secret value

TOKEN_NAME_R2 = "openbao-snapshot-write"  # noqa: S105 - display label for token, not token value
KEY_NAME_B2 = "openbao-snapshot-write"


def _r2_session_and_groups() -> tuple[requests.Session, str, dict]:
    token = r2_rotation_token()
    account_id = require_cache_file(
        "cloudflare-r2-account-id",
        "Already required for cloud-sync.md's endpoint — same file, no new step.",
    )
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    return session, account_id, r2_permission_group_ids(session, account_id)


def mint_r2() -> bool:
    if cached(CACHE_R2_ACCESS) and cached(CACHE_R2_SECRET):
        print("r2 openbao-snapshot-write: already cached, skipping")
        return True

    session, account_id, group_by_name = _r2_session_and_groups()
    result = r2_create_leaf_token(session, account_id, group_by_name, "write", bucket=SNAPSHOT_BUCKET_R2, token_name=TOKEN_NAME_R2)
    access_key, secret_key = result["id"], hashlib.sha256(result["value"].encode()).hexdigest()

    ok, detail = verify_leaf_via_rclone(access_key, secret_key, f"https://{account_id}.r2.cloudflarestorage.com", "auto", SNAPSHOT_BUCKET_R2, "write")
    if not ok:
        print(
            f"r2 openbao-snapshot-write: verification FAILED ({detail}) — not cached. Revoke {access_key} by hand in the Cloudflare dashboard.", file=sys.stderr
        )
        return False
    write_cache(CACHE_R2_ACCESS, access_key)
    write_cache(CACHE_R2_SECRET, secret_key)
    print(f"r2 openbao-snapshot-write: cached, verified ({detail})")
    return True


def rotate_r2() -> bool:
    session, account_id, group_by_name = _r2_session_and_groups()
    old_token_id = read_cache(CACHE_R2_ACCESS)

    result = r2_create_leaf_token(session, account_id, group_by_name, "write", bucket=SNAPSHOT_BUCKET_R2, token_name=TOKEN_NAME_R2)
    new_token_id, new_secret_key = result["id"], hashlib.sha256(result["value"].encode()).hexdigest()

    ok, detail = verify_leaf_via_rclone(new_token_id, new_secret_key, f"https://{account_id}.r2.cloudflarestorage.com", "auto", SNAPSHOT_BUCKET_R2, "write")
    if not ok:
        print(
            f"r2 openbao-snapshot-write: new token {new_token_id} failed verification ({detail}). "
            f"Old token {old_token_id or '(none cached)'} left untouched and still in use; "
            f"new token left live but NOT cached or revoked — investigate, then either retry or delete {new_token_id} by hand.",
            file=sys.stderr,
        )
        return False

    if old_token_id:
        try:
            r2_delete_token(session, account_id, old_token_id)
            print(f"r2 openbao-snapshot-write: old token {old_token_id} revoked")
        except RuntimeError as exc:
            print(
                f"r2 openbao-snapshot-write: new token verified and cached, but revoking old token {old_token_id} failed ({exc}) — revoke it by hand.",
                file=sys.stderr,
            )

    write_cache(CACHE_R2_ACCESS, new_token_id)
    write_cache(CACHE_R2_SECRET, new_secret_key)
    print(f"r2 openbao-snapshot-write: rotated, verified ({detail})")
    return True


def mint_b2() -> bool:
    if cached(CACHE_B2_ACCESS) and cached(CACHE_B2_SECRET):
        print("b2 openbao-snapshot-write: already cached, skipping")
        return True

    session, account_id, api_url = b2_rotation_session()
    bucket_id = b2_lookup_bucket_id(session, api_url, account_id, bucket_name=SNAPSHOT_BUCKET_B2)
    resp = session.post(
        f"{api_url}/b2api/v2/b2_create_key",
        json={
            "accountId": account_id,
            "capabilities": B2_LEAF_CAPABILITIES["write"],
            "keyName": KEY_NAME_B2,
            "bucketId": bucket_id,
            "validDurationInSeconds": QUARTERLY_SECONDS,
        },
    )
    resp.raise_for_status()
    body = resp.json()
    access_key, secret_key = body["applicationKeyId"], body["applicationKey"]

    region = require_cache_file("backblaze-b2-region", "Set via bootstrap_secrets.py / secrets_registry.yaml — same value cloud-sync.md's rclone.conf uses.")
    ok, detail = verify_leaf_via_rclone(access_key, secret_key, f"https://s3.{region}.backblazeb2.com", region, SNAPSHOT_BUCKET_B2, "write")
    if not ok:
        print(f"b2 openbao-snapshot-write: verification FAILED ({detail}) — not cached. Revoke {access_key} by hand in the B2 Console.", file=sys.stderr)
        return False
    write_cache(CACHE_B2_ACCESS, access_key)
    write_cache(CACHE_B2_SECRET, secret_key)
    print(f"b2 openbao-snapshot-write: cached, verified ({detail})")
    return True


def rotate_b2() -> bool:
    session, account_id, api_url = b2_rotation_session()
    bucket_id = b2_lookup_bucket_id(session, api_url, account_id, bucket_name=SNAPSHOT_BUCKET_B2)
    old_key_id = read_cache(CACHE_B2_ACCESS)

    resp = session.post(
        f"{api_url}/b2api/v2/b2_create_key",
        json={
            "accountId": account_id,
            "capabilities": B2_LEAF_CAPABILITIES["write"],
            "keyName": KEY_NAME_B2,
            "bucketId": bucket_id,
            "validDurationInSeconds": QUARTERLY_SECONDS,
        },
    )
    resp.raise_for_status()
    body = resp.json()
    new_key_id, new_app_key = body["applicationKeyId"], body["applicationKey"]

    region = require_cache_file("backblaze-b2-region", "Set via bootstrap_secrets.py / secrets_registry.yaml — same value cloud-sync.md's rclone.conf uses.")
    ok, detail = verify_leaf_via_rclone(new_key_id, new_app_key, f"https://s3.{region}.backblazeb2.com", region, SNAPSHOT_BUCKET_B2, "write")
    if not ok:
        print(
            f"b2 openbao-snapshot-write: new key {new_key_id} failed verification ({detail}). "
            f"Old key {old_key_id or '(none cached)'} left untouched and still in use; "
            f"new key left live but NOT cached or revoked — investigate, then either retry or delete {new_key_id} by hand.",
            file=sys.stderr,
        )
        return False

    if old_key_id:
        try:
            session.post(f"{api_url}/b2api/v2/b2_delete_key", json={"applicationKeyId": old_key_id}).raise_for_status()
            print(f"b2 openbao-snapshot-write: old key {old_key_id} revoked")
        except requests.HTTPError as exc:
            print(
                f"b2 openbao-snapshot-write: new key verified and cached, but revoking old key {old_key_id} failed ({exc}) — revoke it by hand.",
                file=sys.stderr,
            )

    write_cache(CACHE_B2_ACCESS, new_key_id)
    write_cache(CACHE_B2_SECRET, new_app_key)
    print(f"b2 openbao-snapshot-write: rotated, verified ({detail})")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["r2", "b2", "all"], default="all")
    parser.add_argument(
        "--rotate", action="store_true", help="Rotate: mint a new key, verify it, only then revoke the old one. Requires --provider r2 or b2 (not all)."
    )
    args = parser.parse_args()

    SECRETS_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)

    if args.rotate:
        if args.provider not in ("r2", "b2"):
            parser.error("--rotate requires --provider r2 or b2")
        rotate_fn = {"r2": rotate_r2, "b2": rotate_b2}[args.provider]
        try:
            ok = rotate_fn()
        except requests.HTTPError as exc:
            print(f"{args.provider}: request failed: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
            return 1
        return 0 if ok else 1

    mint_fns = {"r2": mint_r2, "b2": mint_b2}
    targets = mint_fns if args.provider == "all" else {args.provider: mint_fns[args.provider]}
    all_ok = True
    for name, fn in targets.items():
        try:
            if not fn():
                all_ok = False
        except requests.HTTPError as exc:
            print(f"{name}: request failed: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
            all_ok = False
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
