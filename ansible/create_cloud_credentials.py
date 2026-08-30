#!/usr/bin/env python3
"""Create the 6 cloud_sync credentials (write+read x R2/B2/OCI) via each
provider's HTTP API instead of a console click-through, and cache them at
the same ansible/files/secrets/<registry-key> paths bootstrap_secrets.py
would have written by hand. Entries stay format: manual in
secrets_registry.yaml — this script is just an automated way to fill
them in. See docs/cloud-credential-creation.md for the exact grant
each leg gets, provider-by-provider.

Authenticates to each provider using a rotation-key credential —
narrower than the account's master credential, created once by
ansible/create_rotation_keys.py — never the raw master key itself. If
a rotation-key cache file is missing, this script tells you which
`create_rotation_keys.py --provider <x>` to run first.

Safe to re-run: a credential whose both cache files already exist is
left untouched, same convention as bootstrap_secrets.py. To rotate one,
delete its cache file(s) under ansible/files/secrets/ first — see
docs/secrets-rotation.md.

Usage:
    python3 ansible/create_cloud_credentials.py [--provider {r2,b2,oci,all}]
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import requests
from oci.signer import Signer as OCISigner

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRETS_DIR = PROJECT_ROOT / "ansible/files/secrets"

R2_BUCKET = "homelab-backups"
B2_BUCKET = "homelab-backups-b2"


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

    token = require_cache_file(
        "_rotation-key-cloudflare-r2-token",
        "Run: python3 ansible/create_rotation_keys.py --provider r2",
    )
    account_id = require_cache_file(
        "cloudflare-r2-account-id",
        "Already required for cloud-sync.md's endpoint — same file, no new step.",
    )
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    groups = session.get(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens/permission_groups",
    ).json()["result"]
    group_by_name = {g["name"]: g["id"] for g in groups}

    resource_key = f"com.cloudflare.edge.r2.bucket.{account_id}_default_{R2_BUCKET}"

    legs = [
        ("write", "Workers R2 Storage Bucket Item Write", write_done),
        ("read", "Workers R2 Storage Bucket Item Read", read_done),
    ]
    for leg, group_name, done in legs:
        if done:
            continue
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

    rotation_key_id = require_cache_file(
        "_rotation-key-backblaze-b2-key-id",
        "Run: python3 ansible/create_rotation_keys.py --provider b2",
    )
    rotation_key = require_cache_file(
        "_rotation-key-backblaze-b2-application-key",
        "Run: python3 ansible/create_rotation_keys.py --provider b2",
    )
    auth = b2_authorize(rotation_key_id, rotation_key)
    account_id = auth["accountId"]
    api_url = auth["apiUrl"]
    session = requests.Session()
    session.headers["Authorization"] = auth["authorizationToken"]

    bucket_resp = session.post(
        f"{api_url}/b2api/v2/b2_list_buckets",
        json={"accountId": account_id, "bucketName": B2_BUCKET},
    )
    bucket_resp.raise_for_status()
    buckets = bucket_resp.json()["buckets"]
    if not buckets:
        print(f"b2: bucket {B2_BUCKET!r} doesn't exist yet — create it first", file=sys.stderr)
        sys.exit(1)
    bucket_id = buckets[0]["bucketId"]

    # writeFiles without deleteFiles, readFiles without writeFiles — B2's
    # native capability list treats these as independent grants (confirmed
    # via b2_list_keys' own documented response examples). No readFiles on
    # the write leg: NEEDS LIVE VERIFICATION — if rclone copy's
    # skip-already-copied check turns out to need HeadObject rather than
    # ListObjectsV2 for existing objects, B2 maps HeadObject to readFiles,
    # not listFiles, and the nightly run will start failing with 403s.
    # Verify with: rclone copy --dry-run -vv storage:<path> b2:<bucket>
    # against a real write-leg key before trusting this in production.
    legs = [
        ("write", ["listBuckets", "listFiles", "writeFiles"], write_done),
        ("read", ["listBuckets", "listFiles", "readFiles"], read_done),
    ]
    for leg, capabilities, done in legs:
        if done:
            continue
        resp = session.post(
            f"{api_url}/b2api/v2/b2_create_key",
            json={
                "accountId": account_id,
                "capabilities": capabilities,
                "keyName": f"homelab-cloud-sync-{leg}",
                "bucketId": bucket_id,
            },
        )
        resp.raise_for_status()
        body = resp.json()
        write_cache(f"backblaze-b2-{leg}-access-key", body["applicationKeyId"])
        write_cache(f"backblaze-b2-{leg}-secret-key", body["applicationKey"])
        print(f"b2 {leg}: cached")


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

    def post(path: str, body: dict) -> dict:
        resp = session.post(f"{endpoint}{path}", json=body)
        resp.raise_for_status()
        return resp.json()

    legs = [("write", write_done), ("read", read_done)]
    for leg, done in legs:
        if done:
            continue
        user_id = require_cache_file(
            f"_oci-leg-user-ocid-{leg}",
            f"Missing the {leg}-leg IAM user's OCID — run: "
            "python3 ansible/create_rotation_keys.py --provider oci",
        )
        key = post(f"/20160918/users/{user_id}/customerSecretKeys", {"displayName": f"homelab-cloud-sync-{leg}"})
        write_cache(f"oci-{leg}-access-key", key["id"])
        # The secret is only ever returned on this create call — nothing
        # to read back later if this write is lost mid-run.
        write_cache(f"oci-{leg}-secret-key", key["key"])
        print(f"oci {leg}: cached")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["r2", "b2", "oci", "all"], default="all")
    args = parser.parse_args()

    SECRETS_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)

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
