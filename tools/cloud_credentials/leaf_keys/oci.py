"""OCI Object Storage leaf-key create/rotate logic, via Identity
Domains SCIM (see ADR 0016) - not oci.signer.Signer / the classic
Identity API this repo used before. Every call below goes through
oci.identity_domains.IdentityDomainsClient, authenticated with a
Bearer token from OAuth2 client-credentials (oci_scim.py) via a custom
signer - see oci_scim.py's oci_identity_domains_client().
"""

from __future__ import annotations

import sys

import oci.exceptions
from oci.identity_domains.models import CustomerSecretKey, CustomerSecretKeyUser

from cloud_credentials.cache import scoped
from cloud_credentials.expiry import QUARTERLY_DAYS, rfc3339_in
from cloud_credentials.rotation_keys.oci_scim import SCIM_CUSTOMER_SECRET_KEY_SCHEMA, oci_identity_domains_client
from cloud_credentials.verify import verify_leaf_via_rclone

cached, read_cache, write_cache, require_cache_file = scoped("leaf")
# oci_leaf_user_id() below reads the rotation-tier IAM user OCID
# rotation_keys/oci_bootstrap.py writes during rotation-key bootstrap -
# a second, differently-scoped binding, same reasoning as leaf_keys/b2.py's.
_, _, _, _rotation_require_cache_file = scoped("rotation")

OCI_BUCKET = "homelab-backups"


def oci_leaf_user_id(leaf: str) -> str:
    return _rotation_require_cache_file(
        f"_oci-leaf-user-ocid-{leaf}",
        f"Missing the {leaf}-leaf IAM user's OCID — run: python3 -m cloud_credentials.create_rotation_keys --provider oci",
    )


def _create_customer_secret_key(client, leaf: str) -> CustomerSecretKey:
    key = CustomerSecretKey(
        schemas=[SCIM_CUSTOMER_SECRET_KEY_SCHEMA],
        display_name=f"homelab-cloud-sync-{leaf}",
        expires_on=rfc3339_in(QUARTERLY_DAYS),
        # user.ocid, not user.value - value is a different, shorter
        # SCIM-internal id (max 40 chars) and rejects an OCID outright.
        user=CustomerSecretKeyUser(ocid=oci_leaf_user_id(leaf)),
    )
    return client.create_customer_secret_key(customer_secret_key=key).data


def _delete_customer_secret_key(client, scim_id: str) -> None:
    client.delete_customer_secret_key(customer_secret_key_id=scim_id)


def create_oci() -> None:
    # All three, not just access-key/secret-key: a leaf with those two
    # cached but no scim-id (e.g. from an interrupted run, or a cache
    # write that happened outside this function) would otherwise look
    # "done" forever and never get its scim-id backfilled - the exact
    # gap that made a genuinely-in-use key show up as an ORPHAN in
    # openbao_utils/audit.py, since that comparison has nothing to match
    # against without it.
    write_done = cached("oci-write-access-key") and cached("oci-write-secret-key") and cached("oci-write-scim-id")
    read_done = cached("oci-read-access-key") and cached("oci-read-secret-key") and cached("oci-read-scim-id")
    if write_done and read_done:
        print("oci: both credentials already cached, skipping")
        return

    # Deliberately does NOT create the homelab-cloud-sync-write/read
    # users, groups, or policies — create_rotation_keys.py does that
    # once, using your personal admin identity. That part is unrelated
    # classic-IAM policy scoping and unaffected by ADR 0016 — only the
    # secret-key material itself now comes from SCIM.
    client = oci_identity_domains_client()

    for leaf, done in [("write", write_done), ("read", read_done)]:
        if done:
            continue
        key = _create_customer_secret_key(client, leaf)
        write_cache(f"oci-{leaf}-access-key", key.access_key)
        # The secret is only ever returned on this create call — same
        # one-time disclosure as the classic API's own `key` field.
        write_cache(f"oci-{leaf}-secret-key", key.secret_key)
        # The SCIM resource id, not the access key itself — needed
        # later to GET/DELETE this exact key (rotation, freshness
        # checks). expiresOn is native now, so unlike before there's
        # no companion -created-at cache file to write. See ADR 0016.
        write_cache(f"oci-{leaf}-scim-id", key.id)
        print(f"oci {leaf}: cached")


def rotate_oci(leaves: list[str]) -> bool:
    client = oci_identity_domains_client()

    namespace = require_cache_file("oci-namespace", "Set via openbao_utils/bootstrap.py / secrets_registry.yaml.")
    region = require_cache_file("oci-region", "Set via openbao_utils/bootstrap.py / secrets_registry.yaml.")
    api_endpoint = f"https://{namespace}.compat.objectstorage.{region}.oraclecloud.com"

    all_ok = True
    for leaf in leaves:
        old_scim_id = read_cache(f"oci-{leaf}-scim-id")

        new_key = _create_customer_secret_key(client, leaf)
        new_access_key, new_secret_key = new_key.access_key, new_key.secret_key

        ok, detail = verify_leaf_via_rclone(new_access_key, new_secret_key, api_endpoint, region, OCI_BUCKET, leaf)
        if not ok:
            print(
                f"oci {leaf}: new key {new_key.id} failed verification ({detail}). "
                f"Old key {old_scim_id or '(none cached)'} left untouched and still in use; "
                f"new key left live but NOT cached or revoked — investigate, then either "
                f"retry or delete it by hand: DELETE {client.base_client.endpoint}/admin/v1/CustomerSecretKeys/{new_key.id}",
                file=sys.stderr,
            )
            all_ok = False
            continue

        write_cache(f"oci-{leaf}-access-key", new_access_key)
        write_cache(f"oci-{leaf}-secret-key", new_secret_key)
        write_cache(f"oci-{leaf}-scim-id", new_key.id)

        if old_scim_id:
            try:
                _delete_customer_secret_key(client, old_scim_id)
                print(f"oci {leaf}: old key {old_scim_id} revoked")
            except oci.exceptions.ServiceError as exc:
                print(
                    f"oci {leaf}: new key cached, but revoking old key {old_scim_id} failed ({exc}) — revoke it by hand.",
                    file=sys.stderr,
                )

        print(f"oci {leaf}: rotated and verified")

    return all_ok
