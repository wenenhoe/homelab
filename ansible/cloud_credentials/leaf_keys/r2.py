"""Cloudflare R2 leaf-key create/rotate logic."""

from __future__ import annotations

import getpass
import hashlib
import sys

import requests

from cloud_credentials.cache import cached, read_cache, require_cache_file, write_cache
from cloud_credentials.expiry import QUARTERLY_DAYS, rfc3339_in
from cloud_credentials.verify import verify_leaf_via_rclone

R2_BUCKET = "homelab-backups"

R2_PERMISSION_GROUP_BY_LEAF = {
    "write": "Workers R2 Storage Bucket Item Write",
    "read": "Workers R2 Storage Bucket Item Read",
}


def r2_rotation_token() -> str:
    """The Cloudflare admin token used to create/revoke R2 leaf tokens.

    Cached from here on — a deliberate, accepted risk, not an oversight.
    This token needs "Account API Tokens: Edit", which Cloudflare will
    only let a human grant via the Console (confirmed live: the tokens
    API rejects granting that permission to any token minted via the
    API itself — "sub-token is not allowed to have permissions to
    manage other tokens"). That restriction is about *creating* such a
    token, not about *reusing* one a human already created; caching it
    doesn't work around anything, it just stops re-prompting for a
    value that was always going to be the same one from the user's
    password manager. The real trade-off: unlike B2's/OCI's rotation
    keys, Cloudflare has no equivalent of "manage users but only
    R2-related permissions" — this credential can mint a token with
    *any* permission the account holder has, not just R2 ones. See
    docs/cloud-credential-creation.md's R2 section for why that's
    accepted rather than avoided, and what narrows the blast radius in
    the meantime (a future secrets-manager migration is the intended
    next mitigation, not this script).
    """
    cache_key = "_rotation-key-cloudflare-r2-token"
    cached_value = read_cache(cache_key)
    if cached_value is not None:
        return cached_value
    print(
        "Cloudflare admin token — a Custom Token named "
        "'homelab-cloud-sync-r2-rotation-key' (NOT the 'Create Additional "
        "Tokens' template) with 'Account' > 'Account API Tokens' > 'Edit' "
        "permission, scoped to this account (dashboard.cloudflare.com > My "
        "Profile > API Tokens) — set an expiration date on it in the "
        "Console (this script can't set one after the fact; "
        "check_freshness.py reads it back live either way) — input "
        "hidden, cached after this:"
    )
    token = getpass.getpass("> ")
    write_cache(cache_key, token)
    return token


def r2_permission_group_ids(session, account_id: str) -> dict:
    resp = session.get(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens/permission_groups",
    ).json()
    if not resp.get("success"):
        print(f"r2: listing permission groups failed: {resp.get('errors')}", file=sys.stderr)
        sys.exit(1)
    return {g["name"]: g["id"] for g in resp["result"]}


def r2_create_leaf_token(session, account_id: str, group_by_name: dict, leaf: str) -> dict:
    group_name = R2_PERMISSION_GROUP_BY_LEAF[leaf]
    if group_name not in group_by_name:
        available = ", ".join(sorted(group_by_name))
        print(
            f"r2 {leaf}: no permission group named {group_name!r} found. Available account-scoped permission groups: {available}",
            file=sys.stderr,
        )
        sys.exit(1)
    resource_key = f"com.cloudflare.edge.r2.bucket.{account_id}_default_{R2_BUCKET}"
    resp = session.post(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens",
        json={
            "name": f"homelab-cloud-sync-r2-{leaf}",
            "policies": [
                {
                    "effect": "allow",
                    "resources": {resource_key: "*"},
                    "permission_groups": [{"id": group_by_name[group_name]}],
                }
            ],
            # Native, confirmed against Cloudflare's own Create Token
            # reference (top-level `expires_on`, RFC 3339, on the same
            # POST /accounts/{account_id}/tokens this already calls) -
            # unlike OCI, no self-tracked cache file needed here.
            # check_freshness.py reads this back live via Get Token
            # rather than trusting a local clock.
            "expires_on": rfc3339_in(QUARTERLY_DAYS),
        },
    ).json()
    if not resp.get("success"):
        print(f"r2 {leaf}: token creation failed: {resp['errors']}", file=sys.stderr)
        sys.exit(1)
    return resp["result"]


def r2_delete_token(session, account_id: str, token_id: str) -> None:
    resp = session.delete(f"https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens/{token_id}").json()
    if not resp.get("success"):
        raise RuntimeError(f"delete failed: {resp.get('errors')}")


def create_r2() -> None:
    write_done = cached("cloudflare-r2-write-access-key") and cached("cloudflare-r2-write-secret-key")
    read_done = cached("cloudflare-r2-read-access-key") and cached("cloudflare-r2-read-secret-key")
    if write_done and read_done:
        print("r2: both credentials already cached, skipping")
        return

    token = r2_rotation_token()
    account_id = require_cache_file(
        "cloudflare-r2-account-id",
        "Already required for cloud-sync.md's endpoint — same file, no new step.",
    )
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    group_by_name = r2_permission_group_ids(session, account_id)

    for leaf, done in [("write", write_done), ("read", read_done)]:
        if done:
            continue
        result = r2_create_leaf_token(session, account_id, group_by_name, leaf)
        # Cloudflare's own docs: Secret Access Key = SHA-256 hash of the
        # token value, computed locally — the raw token value itself is
        # never the S3 secret key. https://developers.cloudflare.com/r2/api/tokens/
        secret_key = hashlib.sha256(result["value"].encode()).hexdigest()
        write_cache(f"cloudflare-r2-{leaf}-access-key", result["id"])
        write_cache(f"cloudflare-r2-{leaf}-secret-key", secret_key)
        print(f"r2 {leaf}: cached")


def rotate_r2(leaves: list[str]) -> bool:
    token = r2_rotation_token()
    account_id = require_cache_file(
        "cloudflare-r2-account-id",
        "Already required for cloud-sync.md's endpoint — same file, no new step.",
    )
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    group_by_name = r2_permission_group_ids(session, account_id)
    # Confirmed live: R2's S3-compat API only ever uses region "auto" —
    # https://developers.cloudflare.com/r2/api/s3/api/. Unlike OCI, it's
    # explicitly lenient about near-misses (empty or us-east-1 also
    # alias to auto), so there's no equivalent risk of a silent
    # SignatureDoesNotMatch from getting this wrong.
    endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    region = "auto"

    all_ok = True
    for leaf in leaves:
        old_token_id = read_cache(f"cloudflare-r2-{leaf}-access-key")

        result = r2_create_leaf_token(session, account_id, group_by_name, leaf)
        new_token_id = result["id"]
        new_secret_key = hashlib.sha256(result["value"].encode()).hexdigest()

        ok, detail = verify_leaf_via_rclone(new_token_id, new_secret_key, endpoint, region, R2_BUCKET, leaf)
        if not ok:
            print(
                f"r2 {leaf}: new token {new_token_id} failed verification ({detail}). "
                f"Old token {old_token_id or '(none cached)'} left untouched and still in use; "
                f"new token left live but NOT cached or revoked — investigate, then either "
                f"retry or delete {new_token_id} by hand in the Cloudflare dashboard.",
                file=sys.stderr,
            )
            all_ok = False
            continue

        if old_token_id:
            try:
                r2_delete_token(session, account_id, old_token_id)
                print(f"r2 {leaf}: old token {old_token_id} revoked")
            except RuntimeError as exc:
                print(
                    f"r2 {leaf}: new token verified and will be cached, but revoking old token "
                    f"{old_token_id} failed ({exc}) — revoke it by hand in the Cloudflare dashboard.",
                    file=sys.stderr,
                )

        write_cache(f"cloudflare-r2-{leaf}-access-key", new_token_id)
        write_cache(f"cloudflare-r2-{leaf}-secret-key", new_secret_key)
        print(f"r2 {leaf}: rotated and verified")

    return all_ok
