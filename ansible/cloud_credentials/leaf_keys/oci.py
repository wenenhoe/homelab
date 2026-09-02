"""OCI Object Storage leaf-key create/rotate logic.

oci.signer.Signer is the OCI SDK's own request-signing helper — a
requests-compatible auth object, not the oci CLI binary and not one of
the generated per-service SDK clients. It implements OCI's Signature
Version 1 scheme (RSA-SHA256 over a canonical header set) so this
module doesn't reimplement request signing by hand; every call below is
still a direct requests.post/get, not a client-library method call.
"""
from __future__ import annotations

import sys

import requests
from oci.signer import Signer as OCISigner

from cloud_credentials.cache import cache_path, cached, read_cache, require_cache_file, write_cache
from cloud_credentials.verify import verify_leaf_via_rclone

OCI_BUCKET = "homelab-backups"

how_to_get_it_oci = "Run: python3 -m cloud_credentials.create_rotation_keys --provider oci"


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
        private_key_file_location=str(cache_path("_rotation-key-oci-private-key.pem")),
    )
    endpoint = f"https://identity.{region}.oraclecloud.com"
    return signer, endpoint


def oci_leaf_user_id(leaf: str) -> str:
    return require_cache_file(
        f"_oci-leaf-user-ocid-{leaf}",
        f"Missing the {leaf}-leaf IAM user's OCID — run: "
        "python3 -m cloud_credentials.create_rotation_keys --provider oci",
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
        old_key_id = read_cache(f"oci-{leaf}-access-key")

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
