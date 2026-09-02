#!/usr/bin/env python3
"""Create the 6 cloud_sync credentials (write+read x R2/B2/OCI) via each
provider's HTTP API instead of a console click-through, and cache them at
the same ansible/files/secrets/<registry-key> paths bootstrap_secrets.py
would have written by hand. Entries stay format: manual in
secrets_registry.yaml — this script is just an automated way to fill
them in. See docs/cloud-credential-creation.md for the exact grant
each leg gets, provider-by-provider.

B2 and OCI authenticate using a rotation-key credential — narrower
than the account's master credential, created once by
ansible/create_rotation_keys.py — never the raw master key itself. If
a rotation-key cache file is missing for either, this script tells you
which `create_rotation_keys.py --provider <x>` to run first.

R2 has no rotation-key tier at all — confirmed live: Cloudflare
rejects granting "manage other tokens" permission to any
API-created token, so there is no delegate credential to cache. R2's
leg is prompted for the master token directly, in memory only, every
time it actually needs to create a leg token. See
docs/cloud-credential-creation.md's R2 section.

Safe to re-run: a credential whose both cache files already exist is
left untouched, same convention as bootstrap_secrets.py.

To rotate a B2/OCI leg key with verify-before-revoke of the old one
(the new key must actually pass a live read/write check over the same
rclone S3-compatible path production uses before the old key is
touched), use --rotate instead of deleting cache files — see
docs/cloud-credential-creation.md's Rotation section. --rotate isn't
available for R2: there's no rotation-key tier to authenticate the
revoke call unattended, so R2 rotation stays the delete-cache-and-rerun
flow it's always been (docs/secrets-rotation.md).

Usage:
    python3 ansible/create_cloud_credentials.py [--provider {r2,b2,oci,all}]
    python3 ansible/create_cloud_credentials.py --provider {b2,oci} --rotate {write,read,both}
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
# overwrites, per this doc's Threat model section). The write leg
# deliberately has no delete capability on either provider (see this
# doc), so these accumulate forever — accepted cost, since rotations are
# rare and each marker is a few bytes.
def _verify_marker_key(leg: str) -> str:
    # time.time_ns() + a random suffix, not just second-resolution
    # time.time() — two verifications in the same second must not
    # collide and silently reintroduce the exact bug this exists to
    # avoid (see this function's header comment).
    return f"_rotation-verify/{leg}-{time.time_ns()}-{secrets.token_hex(4)}"

# OCI-specific, confirmed live twice on two different S3 operations: a
# brand-new customer secret key isn't always usable by Object Storage's
# S3-compat API the instant CreateCustomerSecretKey returns. Retried
# below rather than failed fast — but this means a genuine policy
# problem now ALSO retries the full window before failing, not just a
# real propagation delay. OCI gives no way to tell them apart from the
# response alone:
#   - ListObjects: 403 SignatureDoesNotMatch, "secret key ... could not
#     be found" — confirmed transient (60s and 507s to resolve).
#   - HeadObject (the write leg's rclone pre-flight check before every
#     copy): a bare 403 Forbidden, no distinguishing text at all —
#     confirmed transient too (234s to resolve), but a real policy
#     denial on this same call would look identical. Retrying broadly
#     on "StatusCode: 403" is a deliberate trade-off: a genuinely wrong
#     write-leg policy now takes ~885s to surface as a failure instead
#     of failing instantly. Accepted because the alternative — no
#     retry, so every manual re-run of `--rotate write` mints and
#     orphans a fresh key while propagation finishes — is worse for the
#     common case, and this is a rare, manually-triggered operation.
_PROPAGATION_ERROR_MARKER = "StatusCode: 403"


def _run_rclone_with_retry(cmd: list[str], timeout: int, retries: int = 60, delay: int = 15) -> subprocess.CompletedProcess:
    result = None
    for attempt in range(1, retries + 1):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return result
        if attempt < retries and _PROPAGATION_ERROR_MARKER in result.stderr:
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


def verify_leg_via_rclone(
    access_key: str, secret_key: str, endpoint: str, region: str, bucket: str, leg: str, timeout: int = 45
) -> tuple[bool, str]:
    """Prove a freshly-minted leg key can do its actual job over the same
    rclone S3-compatible path cloud_sync/restore-discovery use in
    production — not just that the provider's native API accepts it.
    B2's own listAllBucketNames/HeadObject surprises (see this doc's B2
    section) are exactly why a native-API success isn't good enough here.

    read: a real ListObjectsV2 (`rclone lsjson`). write: a real PutObject
    (`rclone copyto`) to a fresh, uniquely-named marker key (see
    _verify_marker_key) — rclone's S3 backend does its
    own pre-flight HeadObject before the upload either way, so this
    exercises both calls the write leg actually needs. Returns (ok, detail).

    `region` is required, not optional — confirmed live against OCI: a
    bucket outside the tenancy's home region gets a 403
    SignatureDoesNotMatch with OCI's own error text naming the missing
    region as the cause when rclone's S3 backend signs without one. This
    is the same gap production's rclone.conf.j2 already flags in its own
    header comment as unconfirmed for every remote it renders — not a
    new risk, just the first place in this repo it's actually been hit.
    Included for B2 too on the same principle (matches the endpoint's
    own region, shouldn't be harmful) though that hasn't independently
    hit this failure mode yet.

    Retries on OCI's key-propagation window — see
    _PROPAGATION_ERROR_MARKER — up to ~885s (14m45s) total before
    giving up. Confirmed live three times, across two different S3
    operations: ListObjects took 60s and 507s, HeadObject (the write
    leg's pre-flight check) took 234s — all comfortably inside the
    window, but a real policy problem now also takes the full ~885s to
    surface as a failure rather than failing instantly; see
    _PROPAGATION_ERROR_MARKER's comment for why that trade-off was
    accepted. NEEDS LIVE VERIFICATION: widen further if a real rotation
    exhausts retries.

    `no_check_bucket = true` is required, confirmed live against B2: a
    bucket-restricted key (which both providers' leg keys always are)
    can't satisfy rclone's own pre-flight bucket-existence check, so
    rclone falls back to CreateBucket — which a correctly least-
    privileged key doesn't have rights to, producing a 403 that has
    nothing to do with the object being written. See
    rclone/rclone#4703/#5119 for the same behavior against AWS S3.
    Production's cloud_sync/restore_discovery rclone.conf.j2 templates
    render the same kind of bucket-restricted key and do NOT set this —
    check whether that's actually broken too before assuming it isn't;
    fixing that (if needed) is a separate change from this script.
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

        if leg == "read":
            result = _run_rclone_with_retry([*cmd, "lsjson", f"verify:{bucket}", "--max-depth", "1"], timeout)
            if result.returncode != 0:
                return False, f"rclone lsjson (ListObjectsV2) failed: {result.stderr.strip()}"
            return True, "ListObjectsV2 succeeded"

        marker_path = Path(tmp) / "marker.txt"
        marker_path.write_text(f"homelab rotation-verify marker for the {leg} leg\n")
        result = _run_rclone_with_retry(
            [*cmd, "copyto", str(marker_path), f"verify:{bucket}/{_verify_marker_key(leg)}"], timeout
        )
        if result.returncode != 0:
            return False, f"rclone copyto (PutObject) failed: {result.stderr.strip()}"
        return True, "PutObject succeeded"


# --- Cloudflare R2 ----------------------------------------------------


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

    # No cached rotation key for R2 — confirmed live, not a design
    # choice: Cloudflare rejects granting "manage other tokens"
    # permission to any token created via the API ("sub-token is not
    # allowed to have permissions to manage other tokens"), so there is
    # no way to mint a delegate credential that could stand in for the
    # master token here the way B2's and OCI's rotation keys do. The
    # leg tokens below only need R2-specific permissions, not
    # token-management ones, so they aren't affected by that
    # restriction — only a credential that could itself mint further
    # tokens would be. Master token is prompted fresh every time this
    # actually needs to create a leg token, never cached, same
    # in-memory-only handling as create_rotation_keys.py.
    print(
        "Cloudflare admin token — a Custom Token (NOT the 'Create Additional "
        "Tokens' template) with 'Account' > 'Account API Tokens' > 'Edit' "
        "permission, scoped to this account (dashboard.cloudflare.com > My "
        "Profile > API Tokens) — input hidden, held in memory only:"
    )
    token = getpass.getpass("> ")
    account_id = require_cache_file(
        "cloudflare-r2-account-id",
        "Already required for cloud-sync.md's endpoint — same file, no new step.",
    )
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    groups_resp = session.get(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens/permission_groups",
    ).json()
    if not groups_resp.get("success"):
        print(f"r2: listing permission groups failed: {groups_resp.get('errors')}", file=sys.stderr)
        sys.exit(1)
    group_by_name = {g["name"]: g["id"] for g in groups_resp["result"]}

    resource_key = f"com.cloudflare.edge.r2.bucket.{account_id}_default_{R2_BUCKET}"

    legs = [
        ("write", "Workers R2 Storage Bucket Item Write", write_done),
        ("read", "Workers R2 Storage Bucket Item Read", read_done),
    ]
    for leg, group_name, done in legs:
        if done:
            continue
        if group_name not in group_by_name:
            available = ", ".join(sorted(group_by_name))
            print(
                f"r2 {leg}: no permission group named {group_name!r} found. "
                f"Available account-scoped permission groups: {available}",
                file=sys.stderr,
            )
            sys.exit(1)
        group_id = group_by_name[group_name]
        resp = session.post(
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens",
            json={
                "name": f"homelab-cloud-sync-r2-{leg}",
                "policies": [
                    {
                        "effect": "allow",
                        "resources": {resource_key: "*"},
                        "permission_groups": [{"id": group_id}],
                    }
                ],
            },
        ).json()
        if not resp.get("success"):
            print(f"r2 {leg}: token creation failed: {resp['errors']}", file=sys.stderr)
            sys.exit(1)
        token_id = resp["result"]["id"]
        token_value = resp["result"]["value"]
        # Cloudflare's own docs: Secret Access Key = SHA-256 hash of the
        # token value, computed locally — the raw token value itself is
        # never the S3 secret key. https://developers.cloudflare.com/r2/api/tokens/
        secret_key = hashlib.sha256(token_value.encode()).hexdigest()
        write_cache(f"cloudflare-r2-{leg}-access-key", token_id)
        write_cache(f"cloudflare-r2-{leg}-secret-key", secret_key)
        print(f"r2 {leg}: cached")


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
# readFiles is required on the write leg too, confirmed live. rclone's
# S3 backend calls HeadObject on the destination before every copy,
# fresh object or not, to decide skip-vs-upload — B2 maps HeadObject to
# readFiles, not listFiles. A write leg without readFiles fails
# outright on every copy attempt, not just on already-existing objects.
B2_LEG_CAPABILITIES = {
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


def b2_create_leg_key(session, api_url: str, account_id: str, bucket_id: str, leg: str) -> dict:
    resp = session.post(
        f"{api_url}/b2api/v2/b2_create_key",
        json={
            "accountId": account_id,
            "capabilities": B2_LEG_CAPABILITIES[leg],
            "keyName": f"homelab-cloud-sync-{leg}",
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

    for leg, done in [("write", write_done), ("read", read_done)]:
        if done:
            continue
        body = b2_create_leg_key(session, api_url, account_id, bucket_id, leg)
        write_cache(f"backblaze-b2-{leg}-access-key", body["applicationKeyId"])
        write_cache(f"backblaze-b2-{leg}-secret-key", body["applicationKey"])
        print(f"b2 {leg}: cached")


def rotate_b2(legs: list[str]) -> bool:
    session, account_id, api_url = b2_rotation_session()
    bucket_id = b2_lookup_bucket_id(session, api_url, account_id)
    region = require_cache_file(
        "backblaze-b2-region", "Set via bootstrap_secrets.py / secrets_registry.yaml — same value storage.yaml's rclone.conf uses."
    )
    endpoint = f"https://s3.{region}.backblazeb2.com"

    all_ok = True
    for leg in legs:
        old_key_id = None
        if cached(f"backblaze-b2-{leg}-access-key"):
            old_key_id = (SECRETS_DIR / f"backblaze-b2-{leg}-access-key").read_text().strip()

        new_body = b2_create_leg_key(session, api_url, account_id, bucket_id, leg)
        new_access_key, new_secret_key = new_body["applicationKeyId"], new_body["applicationKey"]

        ok, detail = verify_leg_via_rclone(new_access_key, new_secret_key, endpoint, region, B2_BUCKET, leg)
        if not ok:
            print(
                f"b2 {leg}: new key {new_access_key} failed verification ({detail}). "
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
                print(f"b2 {leg}: old key {old_key_id} revoked")
            except requests.HTTPError as exc:
                print(
                    f"b2 {leg}: new key verified and will be cached, but revoking old key "
                    f"{old_key_id} failed ({exc}) — revoke it by hand in the B2 Console.",
                    file=sys.stderr,
                )

        write_cache(f"backblaze-b2-{leg}-access-key", new_access_key)
        write_cache(f"backblaze-b2-{leg}-secret-key", new_secret_key)
        print(f"b2 {leg}: rotated and verified")

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


def oci_leg_user_id(leg: str) -> str:
    return require_cache_file(
        f"_oci-leg-user-ocid-{leg}",
        f"Missing the {leg}-leg IAM user's OCID — run: "
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

    for leg, done in [("write", write_done), ("read", read_done)]:
        if done:
            continue
        user_id = oci_leg_user_id(leg)
        key = post(f"/20160918/users/{user_id}/customerSecretKeys", {"displayName": f"homelab-cloud-sync-{leg}"})
        write_cache(f"oci-{leg}-access-key", key["id"])
        # The secret is only ever returned on this create call — nothing
        # to read back later if this write is lost mid-run.
        write_cache(f"oci-{leg}-secret-key", key["key"])
        print(f"oci {leg}: cached")


def rotate_oci(legs: list[str]) -> bool:
    signer, endpoint = oci_rotation_auth_and_endpoint()
    session = requests.Session()
    session.auth = signer
    session.headers["Content-Type"] = "application/json"
    post, delete = oci_rotation_calls(session, endpoint)

    namespace = require_cache_file("oci-namespace", "Set via bootstrap_secrets.py / secrets_registry.yaml.")
    region = require_cache_file("oci-region", "Set via bootstrap_secrets.py / secrets_registry.yaml.")
    api_endpoint = f"https://{namespace}.compat.objectstorage.{region}.oraclecloud.com"

    all_ok = True
    for leg in legs:
        user_id = oci_leg_user_id(leg)
        old_key_id = None
        if cached(f"oci-{leg}-access-key"):
            old_key_id = (SECRETS_DIR / f"oci-{leg}-access-key").read_text().strip()

        new_key = post(f"/20160918/users/{user_id}/customerSecretKeys", {"displayName": f"homelab-cloud-sync-{leg}"})
        new_access_key, new_secret_key = new_key["id"], new_key["key"]

        ok, detail = verify_leg_via_rclone(new_access_key, new_secret_key, api_endpoint, region, OCI_BUCKET, leg)
        if not ok:
            print(
                f"oci {leg}: new key {new_access_key} failed verification ({detail}). "
                f"Old key {old_key_id or '(none cached)'} left untouched and still in use; "
                f"new key left live but NOT cached or revoked — investigate, then either "
                f"retry or delete {new_access_key} by hand (Console or DeleteCustomerSecretKey).",
                file=sys.stderr,
            )
            all_ok = False
            continue

        if old_key_id:
            try:
                # NEEDS LIVE VERIFICATION: DELETE on this exact path is
                # inferred from OCI's standard nested-resource REST
                # convention (matches the sibling create call just
                # above), not independently confirmed against Oracle's
                # DeleteCustomerSecretKey reference.
                delete(f"/20160918/users/{user_id}/customerSecretKeys/{old_key_id}")
                print(f"oci {leg}: old key {old_key_id} revoked")
            except requests.HTTPError as exc:
                print(
                    f"oci {leg}: new key verified and will be cached, but revoking old key "
                    f"{old_key_id} failed ({exc}) — revoke it by hand.",
                    file=sys.stderr,
                )

        write_cache(f"oci-{leg}-access-key", new_access_key)
        write_cache(f"oci-{leg}-secret-key", new_secret_key)
        print(f"oci {leg}: rotated and verified")

    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["r2", "b2", "oci", "all"], default="all")
    parser.add_argument(
        "--rotate",
        choices=["write", "read", "both"],
        help=(
            "Rotate a leg key: create a new one, verify it over the same rclone "
            "S3-compatible path production uses, only then revoke the old one. "
            "Requires --provider b2 or oci (not r2 or all) — see this script's "
            "module docstring."
        ),
    )
    args = parser.parse_args()

    SECRETS_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)

    if args.rotate:
        if args.provider not in ("b2", "oci"):
            parser.error("--rotate requires --provider b2 or oci")
        legs = ["write", "read"] if args.rotate == "both" else [args.rotate]
        rotate_fn = {"b2": rotate_b2, "oci": rotate_oci}[args.provider]
        try:
            ok = rotate_fn(legs)
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
