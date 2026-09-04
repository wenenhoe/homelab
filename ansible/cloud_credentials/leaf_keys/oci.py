"""OCI Object Storage leaf-key create/rotate logic, via Identity
Domains SCIM (see ADR 0016) - not oci.signer.Signer / the classic
Identity API this repo used before. Every call below is a direct
requests call against the SCIM admin API, authenticated with a Bearer
token from OAuth2 client-credentials (oci_scim.py).
"""

from __future__ import annotations

import sys

import requests

from cloud_credentials.cache import cached, read_cache, require_cache_file, write_cache
from cloud_credentials.expiry import QUARTERLY_DAYS, rfc3339_in
from cloud_credentials.rotation_keys.oci_scim import SCIM_CUSTOMER_SECRET_KEY_SCHEMA, oci_scim_session
from cloud_credentials.verify import verify_leaf_via_rclone

OCI_BUCKET = "homelab-backups"

how_to_get_it_oci = "Run: python3 -m cloud_credentials.create_rotation_keys --provider oci"


def oci_leaf_user_id(leaf: str) -> str:
    return require_cache_file(
        f"_oci-leaf-user-ocid-{leaf}",
        f"Missing the {leaf}-leaf IAM user's OCID — run: python3 -m cloud_credentials.create_rotation_keys --provider oci",
    )


def _create_customer_secret_key(session: requests.Session, domain_url: str, leaf: str) -> dict:
    body = {
        "schemas": [SCIM_CUSTOMER_SECRET_KEY_SCHEMA],
        "displayName": f"homelab-cloud-sync-{leaf}",
        "expiresOn": rfc3339_in(QUARTERLY_DAYS),
        # user.ocid, not user.value - value is a different, shorter
        # SCIM-internal id (max 40 chars) and rejects an OCID outright.
        # Confirmed live in spikes/oci_scim_oauth_check.py.
        "user": {"ocid": oci_leaf_user_id(leaf)},
    }
    resp = session.post(f"{domain_url}/admin/v1/CustomerSecretKeys", json=body)
    resp.raise_for_status()
    return resp.json()


def _delete_customer_secret_key(session: requests.Session, domain_url: str, scim_id: str) -> None:
    session.delete(f"{domain_url}/admin/v1/CustomerSecretKeys/{scim_id}").raise_for_status()


def create_oci() -> None:
    write_done = cached("oci-write-access-key") and cached("oci-write-secret-key")
    read_done = cached("oci-read-access-key") and cached("oci-read-secret-key")
    if write_done and read_done:
        print("oci: both credentials already cached, skipping")
        return

    # Deliberately does NOT create the homelab-cloud-sync-write/read
    # users, groups, or policies — create_rotation_keys.py does that
    # once, using your personal admin identity. That part is unrelated
    # classic-IAM policy scoping and unaffected by ADR 0016 — only the
    # secret-key material itself now comes from SCIM.
    session, domain_url = oci_scim_session()

    for leaf, done in [("write", write_done), ("read", read_done)]:
        if done:
            continue
        key = _create_customer_secret_key(session, domain_url, leaf)
        write_cache(f"oci-{leaf}-access-key", key["accessKey"])
        # The secret is only ever returned on this create call — same
        # one-time disclosure as the classic API's own `key` field.
        write_cache(f"oci-{leaf}-secret-key", key["secretKey"])
        # The SCIM resource id, not the access key itself — needed
        # later to GET/DELETE this exact key (rotation, freshness
        # checks). expiresOn is native now, so unlike before there's
        # no companion -created-at cache file to write. See ADR 0016.
        write_cache(f"oci-{leaf}-scim-id", key["id"])
        print(f"oci {leaf}: cached")


def rotate_oci(leaves: list[str]) -> bool:
    session, domain_url = oci_scim_session()

    namespace = require_cache_file("oci-namespace", "Set via bootstrap_secrets.py / secrets_registry.yaml.")
    region = require_cache_file("oci-region", "Set via bootstrap_secrets.py / secrets_registry.yaml.")
    api_endpoint = f"https://{namespace}.compat.objectstorage.{region}.oraclecloud.com"

    all_ok = True
    for leaf in leaves:
        old_scim_id = read_cache(f"oci-{leaf}-scim-id")

        new_key = _create_customer_secret_key(session, domain_url, leaf)
        new_access_key, new_secret_key = new_key["accessKey"], new_key["secretKey"]

        ok, detail = verify_leaf_via_rclone(new_access_key, new_secret_key, api_endpoint, region, OCI_BUCKET, leaf)
        if not ok:
            print(
                f"oci {leaf}: new key {new_key['id']} failed verification ({detail}). "
                f"Old key {old_scim_id or '(none cached)'} left untouched and still in use; "
                f"new key left live but NOT cached or revoked — investigate, then either "
                f"retry or delete it by hand: DELETE {domain_url}/admin/v1/CustomerSecretKeys/{new_key['id']}",
                file=sys.stderr,
            )
            all_ok = False
            continue

        if old_scim_id:
            try:
                _delete_customer_secret_key(session, domain_url, old_scim_id)
                print(f"oci {leaf}: old key {old_scim_id} revoked")
            except requests.HTTPError as exc:
                print(
                    f"oci {leaf}: new key verified and will be cached, but revoking old key {old_scim_id} failed ({exc}) — revoke it by hand.",
                    file=sys.stderr,
                )

        write_cache(f"oci-{leaf}-access-key", new_access_key)
        write_cache(f"oci-{leaf}-secret-key", new_secret_key)
        write_cache(f"oci-{leaf}-scim-id", new_key["id"])
        print(f"oci {leaf}: rotated and verified")

    return all_ok
