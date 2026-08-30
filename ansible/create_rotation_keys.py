#!/usr/bin/env python3
"""One-time-per-rotation-key bootstrap: take each provider's master
credential in memory only (never written to disk, never logged) and use
it to mint a narrower "rotation key" that can create/delete the leg
keys but can't touch backup data itself. ansible/create_cloud_credentials.py
authenticates with the cached rotation key from here on — the master
credential is never read by that script.

See docs/cloud-credential-creation.md for what each provider's rotation
key is actually scoped to (the achievable floor differs a lot by
provider — R2 and OCI both have real, documented limits on how far this
can be narrowed, not a uniform "create/delete keys only" guarantee).

Run this again only when a rotation key itself needs rotating — routine
leg-key rotation is create_cloud_credentials.py's job and doesn't touch
this script or the master credential at all.

Usage:
    python3 ansible/create_rotation_keys.py [--provider {r2,b2,oci,all}]
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from oci.config import from_file as oci_config_from_file
from oci.signer import Signer as OCISigner

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRETS_DIR = PROJECT_ROOT / "ansible/files/secrets"

R2_BUCKET = "homelab-backups"
B2_BUCKET = "homelab-backups-b2"
OCI_BUCKET = "homelab-backups"

# Cloudflare has no way to scope a token-creating token below "can
# create any token" (see docs/cloud-credential-creation.md) — a short
# TTL is the only lever available to limit standing exposure.
R2_ROTATION_KEY_TTL_DAYS = 90


def cached(name: str) -> bool:
    return (SECRETS_DIR / name).exists()


def write_cache(name: str, value: str) -> None:
    dest = SECRETS_DIR / name
    dest.write_text(value)
    dest.chmod(0o600)


# --- Cloudflare R2 ----------------------------------------------------


def create_r2_rotation_key() -> None:
    if cached("_rotation-key-cloudflare-r2-token"):
        print("r2: rotation key already cached, skipping")
        return

    print(
        "Cloudflare admin token, Custom Token with the account-level "
        "'Create Additional Tokens' permission (dashboard.cloudflare.com "
        "> My Profile > API Tokens) — input hidden, held in memory only:"
    )
    master_token = getpass.getpass("> ")
    account_id = (SECRETS_DIR / "cloudflare-r2-account-id").read_text().strip()

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {master_token}"
    groups = session.get(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens/permission_groups",
    ).json()["result"]
    group_id = next(g["id"] for g in groups if g["name"] == "Create Additional Tokens")

    import datetime

    expires_on = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=R2_ROTATION_KEY_TTL_DAYS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    resp = session.post(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens",
        json={
            "name": "homelab-cloud-sync-rotation-key",
            "expires_on": expires_on,
            "policies": [
                {
                    "effect": "allow",
                    # Account-wide, not bucket-scoped — Create Additional
                    # Tokens has no resource restriction narrower than
                    # the account (see docs/cloud-credential-creation.md).
                    "resources": {f"com.cloudflare.api.account.{account_id}": "*"},
                    "permission_groups": [{"id": group_id}],
                }
            ],
        },
    ).json()
    if not resp.get("success"):
        print(f"r2: rotation key creation failed: {resp['errors']}", file=sys.stderr)
        sys.exit(1)
    write_cache("_rotation-key-cloudflare-r2-token", resp["result"]["value"])
    print(f"r2: rotation key cached, expires {expires_on}")


# --- Backblaze B2 -------------------------------------------------------

B2_AUTHORIZE_URL = "https://api.backblazeb2.com/b2api/v2/b2_authorize_account"


def create_b2_rotation_key() -> None:
    if cached("_rotation-key-backblaze-b2-key-id") and cached(
        "_rotation-key-backblaze-b2-application-key"
    ):
        print("b2: rotation key already cached, skipping")
        return

    print("Backblaze B2 master key ID (B2 Console > Application Keys):")
    master_key_id = getpass.getpass("> ")
    print("Backblaze B2 master application key — input hidden, held in memory only:")
    master_key = getpass.getpass("> ")

    resp = requests.get(B2_AUTHORIZE_URL, auth=(master_key_id, master_key))
    resp.raise_for_status()
    auth = resp.json()
    account_id, api_url = auth["accountId"], auth["apiUrl"]
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

    # listKeys/writeKeys/deleteKeys are B2's native "manage other keys"
    # capabilities, independent of writeFiles/readFiles — this key can
    # create and delete application keys but can't read or write file
    # contents itself. NEEDS LIVE VERIFICATION: whether a bucket-restricted
    # key can only create further keys restricted to that same bucket, or
    # can mint an all-bucket key too — Backblaze's docs describe the
    # bucketId restriction field but don't state this constraint
    # explicitly either way. Test with a throwaway key before trusting it.
    key_resp = session.post(
        f"{api_url}/b2api/v2/b2_create_key",
        json={
            "accountId": account_id,
            "capabilities": ["listKeys", "writeKeys", "deleteKeys", "listBuckets"],
            "keyName": "homelab-cloud-sync-rotation-key",
            "bucketId": bucket_id,
        },
    )
    key_resp.raise_for_status()
    body = key_resp.json()
    write_cache("_rotation-key-backblaze-b2-key-id", body["applicationKeyId"])
    write_cache("_rotation-key-backblaze-b2-application-key", body["applicationKey"])
    print("b2: rotation key cached")


# --- OCI Object Storage ---------------------------------------------------


def oci_master_auth_and_endpoint() -> tuple[OCISigner, str, str, str]:
    # ~/.oci/config is read here, and only here — this is your personal
    # admin identity, used once per rotation-key bootstrap. It's never
    # read by create_cloud_credentials.py.
    config = oci_config_from_file()
    signer = OCISigner(
        tenancy=config["tenancy"],
        user=config["user"],
        fingerprint=config["fingerprint"],
        private_key_file_location=config["key_file"],
        pass_phrase=config.get("pass_phrase"),
    )
    endpoint = f"https://identity.{config['region']}.oraclecloud.com"
    return signer, endpoint, config["tenancy"], config["region"]


def oci_ensure_leg_identity(session, endpoint, post, tenancy: str, leg: str, permissions: list[str]) -> str:
    """Create the leg's IAM user/group/policy if missing; return its user OCID.

    Idempotent via 409-on-create — if homelab-cloud-sync-<leg> already
    exists this looks it up instead of failing the whole run.
    """
    cache_key = f"_oci-leg-user-ocid-{leg}"
    if cached(cache_key):
        return (SECRETS_DIR / cache_key).read_text().strip()

    name = f"homelab-cloud-sync-{leg}"
    try:
        user = post(
            "/20160918/users",
            {
                "compartmentId": tenancy,
                "name": name,
                "description": f"cloud_sync {leg} credential for {OCI_BUCKET} — see docs/cloud-credential-creation.md",
            },
        )
    except requests.HTTPError as exc:
        if exc.response.status_code != 409:
            raise
        print(f"oci: user {name} already exists, looking it up instead of recreating it", file=sys.stderr)
        # NEEDS LIVE VERIFICATION: this is OCI's documented ListUsers
        # shape (GET with compartmentId+name query params), but this
        # 409 path hasn't been exercised against a real tenancy — if it
        # 404s or returns more than one match, that's the first thing to
        # check before assuming anything else is wrong.
        resp = session.get(
            f"{endpoint}/20160918/users",
            params={"compartmentId": tenancy, "name": name},
        )
        resp.raise_for_status()
        matches = resp.json()
        if len(matches) != 1:
            print(f"oci: expected exactly one existing user named {name}, found {len(matches)}", file=sys.stderr)
            sys.exit(1)
        user = matches[0]
        write_cache(cache_key, user["id"])
        return user["id"]

    group = post(
        "/20160918/groups",
        {"compartmentId": tenancy, "name": name, "description": f"Grants {name} its bucket-scoped policy"},
    )
    post("/20160918/userGroupMemberships", {"userId": user["id"], "groupId": group["id"]})

    permission_clause = ", ".join(f"request.permission='{p}'" for p in permissions)
    statement = (
        f"Allow group id {group['id']} to manage objects in tenancy "
        f"where all {{target.bucket.name='{OCI_BUCKET}', any {{{permission_clause}}}}}"
    )
    post(
        "/20160918/policies",
        {
            "compartmentId": tenancy,
            "name": name,
            "description": f"Scopes {name} to {OCI_BUCKET}, {leg} only",
            "statements": [statement],
        },
    )
    write_cache(cache_key, user["id"])
    return user["id"]


def oci_create_rotation_identity(post, tenancy: str) -> str:
    """Create the dedicated key-rotation IAM user/group/policy. Returns its user OCID."""
    name = "homelab-key-rotation"
    user = post(
        "/20160918/users",
        {
            "compartmentId": tenancy,
            "name": name,
            "description": "Rotates cloud_sync's OCI customer secret keys — see docs/cloud-credential-creation.md",
        },
    )
    group = post("/20160918/groups", {"compartmentId": tenancy, "name": name, "description": f"Grants {name} its policy"})
    post("/20160918/userGroupMemberships", {"userId": user["id"], "groupId": group["id"]})
    # manage customer-secret-keys, tenancy-wide — NOT scoped to just the
    # two homelab-cloud-sync-* users. NEEDS LIVE VERIFICATION: I found no
    # confirmed OCI policy condition (target.user.name= or similar) that
    # narrows identity-family resources to a specific named user the way
    # target.bucket.name= narrows object storage — see
    # docs/cloud-credential-creation.md. This is the achievable floor,
    # not the ideal: it can rotate ANY user's secret keys in the tenancy,
    # but nothing else (no manage users/groups/policies, no object storage,
    # no compute/network/billing).
    post(
        "/20160918/policies",
        {
            "compartmentId": tenancy,
            "name": name,
            "description": "Scopes homelab-key-rotation to customer secret keys only",
            "statements": [f"Allow group id {group['id']} to manage customer-secret-keys in tenancy"],
        },
    )
    return user["id"]


def create_oci_rotation_key() -> None:
    rotation_files = [
        "_rotation-key-oci-user-ocid",
        "_rotation-key-oci-fingerprint",
        "_rotation-key-oci-private-key.pem",
        "_rotation-key-oci-tenancy-ocid",
        "_rotation-key-oci-region",
    ]
    if all(cached(f) for f in rotation_files):
        print("oci: rotation identity already cached, skipping")
        return

    signer, endpoint, tenancy, region = oci_master_auth_and_endpoint()
    session = requests.Session()
    session.auth = signer
    session.headers["Content-Type"] = "application/json"

    def post(path: str, body: dict) -> dict:
        resp = session.post(f"{endpoint}{path}", json=body)
        resp.raise_for_status()
        return resp.json()

    # OBJECT_INSPECT+OBJECT_CREATE (no OBJECT_DELETE) / OBJECT_INSPECT+
    # OBJECT_READ — confirmed against Oracle's own Policy Builder
    # templates and the Object Storage Objects reference doc.
    oci_ensure_leg_identity(session, endpoint, post, tenancy, "write", ["OBJECT_INSPECT", "OBJECT_CREATE"])
    oci_ensure_leg_identity(session, endpoint, post, tenancy, "read", ["OBJECT_INSPECT", "OBJECT_READ"])

    rotation_user_id = oci_create_rotation_identity(post, tenancy)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    # NEEDS LIVE VERIFICATION: the UploadApiKey request body's JSON field
    # name for the PEM public key — Oracle's docs confirm the operation
    # and that the fingerprint comes back computed in the response, but
    # every source I found described it via SDK/Terraform field names
    # (key_value, keyValue) rather than the raw REST JSON key. "key" is
    # my best-supported guess (matches the Java/Python SDK's UploadApiKeyDetails
    # model); if this 400s, check the exact field name against a live
    # OCI tenancy before changing anything else.
    api_key = post(f"/20160918/users/{rotation_user_id}/apiKeys", {"key": public_pem})

    write_cache("_rotation-key-oci-user-ocid", rotation_user_id)
    write_cache("_rotation-key-oci-fingerprint", api_key["fingerprint"])
    write_cache("_rotation-key-oci-private-key.pem", private_pem)
    write_cache("_rotation-key-oci-tenancy-ocid", tenancy)
    write_cache("_rotation-key-oci-region", region)
    print("oci: rotation identity and leg users cached")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["r2", "b2", "oci", "all"], default="all")
    args = parser.parse_args()

    SECRETS_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)

    providers = {
        "r2": create_r2_rotation_key,
        "b2": create_b2_rotation_key,
        "oci": create_oci_rotation_key,
    }
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
