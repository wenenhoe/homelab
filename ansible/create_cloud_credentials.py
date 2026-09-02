#!/usr/bin/env python3
"""Create the 6 cloud_sync credentials (write+read x R2/B2/OCI) via each
provider's HTTP API instead of a console click-through, and cache them at
the same ansible/files/secrets/<registry-key> paths bootstrap_secrets.py
would have written by hand. Entries stay format: manual in
secrets_registry.yaml — this script is just an automated way to fill
them in. See docs/cloud-credential-creation.md for the exact grant
each leaf gets, provider-by-provider.

B2 and OCI authenticate using a rotation-key credential — narrower
than the account's master credential, created once by
ansible/create_rotation_keys.py — never the raw master key itself. If
a rotation-key cache file is missing for either, this script tells you
which `create_rotation_keys.py --provider <x>` to run first.

R2 caches its admin token too (r2_rotation_token), but it's a
materially different credential than B2's/OCI's rotation keys: it can
mint a token with ANY permission the account holder has, not just
R2-scoped ones, because Cloudflare has no equivalent of "manage tokens
but only for R2 permissions" (confirmed live: the tokens API rejects
granting token-management permission to any API-created token, so this
can only be a human-created Console token in the first place — caching
it doesn't change what it can do, only how often you have to paste it
in). This is a deliberate, accepted risk — see
docs/cloud-credential-creation.md's R2 section for the trade-off and
what's expected to narrow it later (a secrets-manager migration, not
this script).

Safe to re-run: a credential whose both cache files already exist is
left untouched, same convention as bootstrap_secrets.py.

To rotate a leaf key with verify-before-revoke of the old one (the new
key must actually pass a live read/write check over the same rclone
S3-compatible path production uses before the old key is touched), use
--rotate instead of deleting cache files for all three providers now —
see docs/cloud-credential-creation.md's Rotation section.

Usage:
    python3 ansible/create_cloud_credentials.py [--provider {r2,b2,oci,all}]
    python3 ansible/create_cloud_credentials.py --provider {r2,b2,oci} --rotate {write,read,both}
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from oci.signer import Signer as OCISigner

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRETS_DIR = PROJECT_ROOT / "ansible/files/secrets"

R2_BUCKET = "homelab-backups"
B2_BUCKET = "homelab-backups-b2"
OCI_BUCKET = "homelab-backups"

# Unique per verification, never reused: confirmed live that reusing
# one fixed path breaks permanently the moment a bucket has a retention
# rule — the first write creates the object, every later write to that
# same key is a genuine RetentionRuleViolation, not a permissions or
# propagation issue, and it never resolves by waiting. A fresh key
# avoids that entirely, and better matches production anyway (cloud_sync
# uses `rclone copy`, never `sync` — always new objects, never
# overwrites, per this doc's Threat model section). The write leaf
# deliberately has no delete capability on either provider (see this
# doc), so these accumulate forever — accepted cost, since rotations are
# rare and each marker is a few bytes.
def _verify_marker_key(leaf: str) -> str:
    # time.time_ns() + a random suffix, not just second-resolution
    # time.time() — two verifications in the same second must not
    # collide and silently reintroduce the exact bug this exists to
    # avoid (see this function's header comment).
    return f"_rotation-verify/{leaf}-{time.time_ns()}-{secrets.token_hex(4)}"

# A brand-new leaf credential isn't always usable by the provider's
# S3-compat API the instant the create call returns (confirmed live on
# OCI and R2, different HTTP status per provider — see
# docs/cloud-credential-creation.md's Rotation section for specifics).
# Retried broadly on status alone, not specific error text, since
# neither provider distinguishes "not propagated yet" from "genuinely
# denied by policy" in the response — a real policy problem now also
# takes the full window to surface as a failure, accepted because the
# alternative (no retry) orphans a fresh credential on every manual
# re-run instead.
_PROPAGATION_ERROR_MARKERS = ("StatusCode: 403", "StatusCode: 401")


def _run_rclone_with_retry(cmd: list[str], timeout: int, retries: int = 60, delay: int = 15) -> subprocess.CompletedProcess:
    result = None
    for attempt in range(1, retries + 1):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return result
        if attempt < retries and any(marker in result.stderr for marker in _PROPAGATION_ERROR_MARKERS):
            elapsed = attempt * delay
            print(f"  (new key not yet recognized by the provider, attempt {attempt}/{retries}, ~{elapsed}s elapsed — retrying in {delay}s)", file=sys.stderr)
            time.sleep(delay)
            continue
        break
    return result


def cached(name: str) -> bool:
    return (SECRETS_DIR / name).exists()


def write_cache(name: str, value: str) -> None:
    dest = SECRETS_DIR / name
    dest.write_text(value)
    dest.chmod(0o600)


def require_cache_file(name: str, how_to_get_it: str) -> str:
    path = SECRETS_DIR / name
    if not path.exists():
        print(f"Missing required cache file: {name}", file=sys.stderr)
        print(f"  {how_to_get_it}", file=sys.stderr)
        sys.exit(1)
    return path.read_text().strip()


def verify_leaf_via_rclone(
    access_key: str, secret_key: str, endpoint: str, region: str, bucket: str, leaf: str, timeout: int = 45
) -> tuple[bool, str]:
    """Prove a freshly-minted leaf key can do its actual job over the same
    rclone S3-compatible path cloud_sync/restore-discovery use in
    production — not just that the provider's native API accepts it
    (see docs/cloud-credential-creation.md's B2 section for why that
    distinction matters).

    read: a real ListObjectsV2 (`rclone lsjson`). write: a real PutObject
    (`rclone copyto`) to a fresh, uniquely-named marker key (see
    _verify_marker_key) — rclone's S3 backend does its own pre-flight
    HeadObject before the upload either way, so this exercises both
    calls the write leaf actually needs. Returns (ok, detail).

    `region` and `no_check_bucket = true` are both required, not
    optional, and retries run through a real provider propagation
    window — see docs/cloud-credential-creation.md's Rotation section
    for what breaks without each of these and why the retry gate is as
    broad as it is.
    """
    with tempfile.TemporaryDirectory() as tmp:
        conf_path = Path(tmp) / "rclone.conf"
        conf_path.write_text(
            "[verify]\n"
            "type = s3\n"
            "provider = Other\n"
            f"access_key_id = {access_key}\n"
            f"secret_access_key = {secret_key}\n"
            f"endpoint = {endpoint}\n"
            f"region = {region}\n"
            "force_path_style = true\n"
            "no_check_bucket = true\n"
        )
        conf_path.chmod(0o600)
        cmd = ["rclone", "--config", str(conf_path), "--contimeout", "5s", "--timeout", f"{timeout}s", "--low-level-retries", "1"]

        if leaf == "read":
            result = _run_rclone_with_retry([*cmd, "lsjson", f"verify:{bucket}", "--max-depth", "1"], timeout)
            if result.returncode != 0:
                return False, f"rclone lsjson (ListObjectsV2) failed: {result.stderr.strip()}"
            return True, "ListObjectsV2 succeeded"

        marker_path = Path(tmp) / "marker.txt"
        marker_path.write_text(f"homelab rotation-verify marker for the {leaf} leaf\n")
        result = _run_rclone_with_retry(
            [*cmd, "copyto", str(marker_path), f"verify:{bucket}/{_verify_marker_key(leaf)}"], timeout
        )
        if result.returncode != 0:
            return False, f"rclone copyto (PutObject) failed: {result.stderr.strip()}"
        return True, "PutObject succeeded"


# --- Cloudflare R2 ----------------------------------------------------


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
    if cached(cache_key):
        return (SECRETS_DIR / cache_key).read_text().strip()
    print(
        "Cloudflare admin token — a Custom Token named "
        "'homelab-cloud-sync-r2-rotation-key' (NOT the 'Create Additional "
        "Tokens' template) with 'Account' > 'Account API Tokens' > 'Edit' "
        "permission, scoped to this account (dashboard.cloudflare.com > My "
        "Profile > API Tokens) — input hidden, cached after this:"
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
            f"r2 {leaf}: no permission group named {group_name!r} found. "
            f"Available account-scoped permission groups: {available}",
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
    write_done = cached("cloudflare-r2-write-access-key") and cached(
        "cloudflare-r2-write-secret-key"
    )
    read_done = cached("cloudflare-r2-read-access-key") and cached(
        "cloudflare-r2-read-secret-key"
    )
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
        old_token_id = None
        if cached(f"cloudflare-r2-{leaf}-access-key"):
            old_token_id = (SECRETS_DIR / f"cloudflare-r2-{leaf}-access-key").read_text().strip()

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


# --- Backblaze B2 -------------------------------------------------------

B2_AUTHORIZE_URL = "https://api.backblazeb2.com/b2api/v2/b2_authorize_account"


def b2_authorize(key_id: str, key: str) -> dict:
    resp = requests.get(B2_AUTHORIZE_URL, auth=(key_id, key))
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
        "Run: python3 ansible/create_rotation_keys.py --provider b2",
    )
    rotation_key = require_cache_file(
        "_rotation-key-backblaze-b2-application-key",
        "Run: python3 ansible/create_rotation_keys.py --provider b2",
    )
    auth = b2_authorize(rotation_key_id, rotation_key)
    session = requests.Session()
    session.headers["Authorization"] = auth["authorizationToken"]
    return session, auth["accountId"], auth["apiUrl"]


def create_b2() -> None:
    write_done = cached("backblaze-b2-write-access-key") and cached(
        "backblaze-b2-write-secret-key"
    )
    read_done = cached("backblaze-b2-read-access-key") and cached(
        "backblaze-b2-read-secret-key"
    )
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
    region = require_cache_file(
        "backblaze-b2-region", "Set via bootstrap_secrets.py / secrets_registry.yaml — same value storage.yaml's rclone.conf uses."
    )
    endpoint = f"https://s3.{region}.backblazeb2.com"

    all_ok = True
    for leaf in leaves:
        old_key_id = None
        if cached(f"backblaze-b2-{leaf}-access-key"):
            old_key_id = (SECRETS_DIR / f"backblaze-b2-{leaf}-access-key").read_text().strip()

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
                    f"b2 {leaf}: new key verified and will be cached, but revoking old key "
                    f"{old_key_id} failed ({exc}) — revoke it by hand in the B2 Console.",
                    file=sys.stderr,
                )

        write_cache(f"backblaze-b2-{leaf}-access-key", new_access_key)
        write_cache(f"backblaze-b2-{leaf}-secret-key", new_secret_key)
        print(f"b2 {leaf}: rotated and verified")

    return all_ok


# --- OCI Object Storage ---------------------------------------------------

# oci.signer.Signer is the OCI SDK's own request-signing helper — a
# requests-compatible auth object, not the oci CLI binary and not one of
# the generated per-service SDK clients. It implements OCI's Signature
# Version 1 scheme (RSA-SHA256 over a canonical header set) so this
# script doesn't reimplement request signing by hand; every call below
# is still a direct requests.post/get, not a client-library method call.


how_to_get_it_oci = "Run: python3 ansible/create_rotation_keys.py --provider oci"


def oci_rotation_auth_and_endpoint() -> tuple[OCISigner, str]:
    # Built from the rotation identity create_rotation_keys.py created —
    # not ~/.oci/config, which belongs to your personal/admin OCI user
    # and is never read here. That's the whole point: this script's
    # blast radius is capped at whatever the rotation identity's policy
    # grants (manage customer-secret-keys only — see
    # docs/cloud-credential-creation.md), not your personal admin rights.
    user = require_cache_file("_rotation-key-oci-user-ocid", how_to_get_it_oci)
    fingerprint = require_cache_file("_rotation-key-oci-fingerprint", how_to_get_it_oci)
    tenancy = require_cache_file("_rotation-key-oci-tenancy-ocid", how_to_get_it_oci)
    region = require_cache_file("_rotation-key-oci-region", how_to_get_it_oci)
    signer = OCISigner(
        tenancy=tenancy,
        user=user,
        fingerprint=fingerprint,
        private_key_file_location=str(SECRETS_DIR / "_rotation-key-oci-private-key.pem"),
    )
    endpoint = f"https://identity.{region}.oraclecloud.com"
    return signer, endpoint


def oci_leaf_user_id(leaf: str) -> str:
    return require_cache_file(
        f"_oci-leaf-user-ocid-{leaf}",
        f"Missing the {leaf}-leaf IAM user's OCID — run: "
        "python3 ansible/create_rotation_keys.py --provider oci",
    )


def oci_rotation_calls(session, endpoint: str):
    def post(path: str, body: dict) -> dict:
        resp = session.post(f"{endpoint}{path}", json=body)
        resp.raise_for_status()
        return resp.json()

    def delete(path: str) -> None:
        session.delete(f"{endpoint}{path}").raise_for_status()

    return post, delete


def create_oci() -> None:
    write_done = cached("oci-write-access-key") and cached("oci-write-secret-key")
    read_done = cached("oci-read-access-key") and cached("oci-read-secret-key")
    if write_done and read_done:
        print("oci: both credentials already cached, skipping")
        return

    # Deliberately does NOT create the homelab-cloud-sync-write/read
    # users, groups, or policies — create_rotation_keys.py does that
    # once, using your personal admin identity, precisely so this
    # script (the one that runs routinely) never needs IAM-write rights
    # beyond customer-secret-keys. See docs/cloud-credential-creation.md.
    signer, endpoint = oci_rotation_auth_and_endpoint()
    session = requests.Session()
    session.auth = signer
    session.headers["Content-Type"] = "application/json"
    post, _delete = oci_rotation_calls(session, endpoint)

    for leaf, done in [("write", write_done), ("read", read_done)]:
        if done:
            continue
        user_id = oci_leaf_user_id(leaf)
        key = post(f"/20160918/users/{user_id}/customerSecretKeys", {"displayName": f"homelab-cloud-sync-{leaf}"})
        write_cache(f"oci-{leaf}-access-key", key["id"])
        # The secret is only ever returned on this create call — nothing
        # to read back later if this write is lost mid-run.
        write_cache(f"oci-{leaf}-secret-key", key["key"])
        print(f"oci {leaf}: cached")


def rotate_oci(leaves: list[str]) -> bool:
    signer, endpoint = oci_rotation_auth_and_endpoint()
    session = requests.Session()
    session.auth = signer
    session.headers["Content-Type"] = "application/json"
    post, delete = oci_rotation_calls(session, endpoint)

    namespace = require_cache_file("oci-namespace", "Set via bootstrap_secrets.py / secrets_registry.yaml.")
    region = require_cache_file("oci-region", "Set via bootstrap_secrets.py / secrets_registry.yaml.")
    api_endpoint = f"https://{namespace}.compat.objectstorage.{region}.oraclecloud.com"

    all_ok = True
    for leaf in leaves:
        user_id = oci_leaf_user_id(leaf)
        old_key_id = None
        if cached(f"oci-{leaf}-access-key"):
            old_key_id = (SECRETS_DIR / f"oci-{leaf}-access-key").read_text().strip()

        new_key = post(f"/20160918/users/{user_id}/customerSecretKeys", {"displayName": f"homelab-cloud-sync-{leaf}"})
        new_access_key, new_secret_key = new_key["id"], new_key["key"]

        ok, detail = verify_leaf_via_rclone(new_access_key, new_secret_key, api_endpoint, region, OCI_BUCKET, leaf)
        if not ok:
            print(
                f"oci {leaf}: new key {new_access_key} failed verification ({detail}). "
                f"Old key {old_key_id or '(none cached)'} left untouched and still in use; "
                f"new key left live but NOT cached or revoked — investigate, then either "
                f"retry or delete {new_access_key} by hand (Console or DeleteCustomerSecretKey).",
                file=sys.stderr,
            )
            all_ok = False
            continue

        if old_key_id:
            try:
                # Confirmed live: this DELETE path successfully revoked
                # both the read and write leaf's old customer secret key
                # during real rotations this session.
                delete(f"/20160918/users/{user_id}/customerSecretKeys/{old_key_id}")
                print(f"oci {leaf}: old key {old_key_id} revoked")
            except requests.HTTPError as exc:
                print(
                    f"oci {leaf}: new key verified and will be cached, but revoking old key "
                    f"{old_key_id} failed ({exc}) — revoke it by hand.",
                    file=sys.stderr,
                )

        write_cache(f"oci-{leaf}-access-key", new_access_key)
        write_cache(f"oci-{leaf}-secret-key", new_secret_key)
        print(f"oci {leaf}: rotated and verified")

    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["r2", "b2", "oci", "all"], default="all")
    parser.add_argument(
        "--rotate",
        choices=["write", "read", "both"],
        help=(
            "Rotate a leaf key: create a new one, verify it over the same rclone "
            "S3-compatible path production uses, only then revoke the old one. "
            "Requires --provider r2, b2, or oci (not all) — see this script's "
            "module docstring."
        ),
    )
    args = parser.parse_args()

    SECRETS_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)

    if args.rotate:
        if args.provider not in ("r2", "b2", "oci"):
            parser.error("--rotate requires --provider r2, b2, or oci")
        leaves = ["write", "read"] if args.rotate == "both" else [args.rotate]
        rotate_fn = {"r2": rotate_r2, "b2": rotate_b2, "oci": rotate_oci}[args.provider]
        try:
            ok = rotate_fn(leaves)
        except requests.HTTPError as exc:
            print(f"{args.provider}: request failed: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
            return 1
        return 0 if ok else 1

    providers = {"r2": create_r2, "b2": create_b2, "oci": create_oci}
    targets = providers if args.provider == "all" else {args.provider: providers[args.provider]}
    for name, fn in targets.items():
        try:
            fn()
        except requests.HTTPError as exc:
            print(f"{name}: request failed: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
