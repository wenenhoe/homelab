"""OCI leaf-identity and rotation-identity bootstrap: create the IAM
users/groups/policies a fresh tenancy needs, and (re-)verify their
policy statements on every run even once cached.
"""

from __future__ import annotations

import sys

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from cloud_credentials.cache import cached, read_cache, write_cache
from cloud_credentials.rotation_keys.oci_iam import (
    oci_get_or_create_group,
    oci_get_or_create_user,
    oci_lookup_one,
    oci_master_auth_and_endpoint,
)

# Must match leaf_keys/oci.py's OCI_BUCKET exactly - both flows operate
# on the same bucket, one scoping IAM policies to it, the other reading/
# writing objects in it. A drift here would silently policy-scope one
# bucket while cloud_sync/restore_discovery actually use another.
OCI_BUCKET = "homelab-backups"


def oci_ensure_leaf_identity(session, endpoint, post, put, tenancy: str, leaf: str, permissions: list[str], admin_email: str) -> str:
    """Create the leaf's IAM user/group if missing, and always (re-)verify its
    policy statement matches `permissions`; return its user OCID.

    The user/group/membership steps are skipped once `cache_key` exists —
    those never change after creation. The policy step is NOT gated by that
    cache: it 409-and-updates every run, so a permissions-list change here
    (e.g. adding OBJECT_OVERWRITE) actually reaches an already-bootstrapped
    tenancy on the next run, instead of being silently skipped forever the
    way `oci_create_rotation_identity`'s own top-level cache check already
    documents as a known gap for the rotation key — this closes the same
    gap for leaf identities before it bites the same way twice.
    """
    cache_key = f"_oci-leaf-user-ocid-{leaf}"
    name = f"homelab-cloud-sync-{leaf}"

    if cached(cache_key):
        user_id = read_cache(cache_key)
        group = oci_lookup_one(session, endpoint, tenancy, "groups", name)
    else:
        user = oci_get_or_create_user(
            session,
            endpoint,
            post,
            tenancy,
            name,
            f"cloud_sync {leaf} credential for {OCI_BUCKET} — see docs/cloud-credential-creation.md",
            admin_email,
        )
        group = oci_get_or_create_group(session, endpoint, post, tenancy, name, f"Grants {name} its bucket-scoped policy")
        try:
            post("/20160918/userGroupMemberships", {"userId": user["id"], "groupId": group["id"]})
        except requests.HTTPError as exc:
            if exc.response.status_code != 409:
                raise
            print(f"oci: {name} is already a member of its group, skipping", file=sys.stderr)
        user_id = user["id"]

    permission_clause = ", ".join(f"request.permission='{p}'" for p in permissions)
    statement = f"Allow group id {group['id']} to manage objects in tenancy where all {{target.bucket.name='{OCI_BUCKET}', any {{{permission_clause}}}}}"
    try:
        post(
            "/20160918/policies",
            {
                "compartmentId": tenancy,
                "name": name,
                "description": f"Scopes {name} to {OCI_BUCKET}, {leaf} only",
                "statements": [statement],
            },
        )
    except requests.HTTPError as exc:
        if exc.response.status_code != 409:
            raise
        print(f"oci: policy {name} already exists, updating its statements", file=sys.stderr)
        existing = oci_lookup_one(session, endpoint, tenancy, "policies", name)
        put(f"/20160918/policies/{existing['id']}", {"statements": [statement]})

    write_cache(cache_key, user_id)
    return user_id


def oci_ensure_rotation_identity(session, endpoint, post, put, tenancy: str, admin_email: str) -> str:
    """Create the dedicated key-rotation IAM user/group, and always
    (re-)verify its policy statement. Returns its user OCID.

    Mirrors oci_ensure_leaf_identity's split: user/group/membership are
    skipped once they exist, but the policy 409-and-updates every call —
    so this is safe (and cheap) to run unconditionally, independent of
    whether the rotation keypair itself is already cached. See
    docs/cloud-credential-creation.md's Known gap entry for why that
    split matters here specifically.
    """
    name = "homelab-key-rotation"
    user = oci_get_or_create_user(
        session,
        endpoint,
        post,
        tenancy,
        name,
        "Rotates cloud_sync's OCI customer secret keys — see docs/cloud-credential-creation.md",
        admin_email,
    )
    group = oci_get_or_create_group(session, endpoint, post, tenancy, name, f"Grants {name} its policy")
    try:
        post("/20160918/userGroupMemberships", {"userId": user["id"], "groupId": group["id"]})
    except requests.HTTPError as exc:
        if exc.response.status_code != 409:
            raise
        print(f"oci: {name} is already a member of its group, skipping", file=sys.stderr)

    # manage users + permission-level conditions — not "manage
    # customer-secret-keys". That resource-type doesn't exist in OCI's
    # policy language; OCI rejected it outright with 400 "No permissions
    # found" (confirmed live).
    #
    # USER_UPDATE is required alongside USER_SECRETKEY_ADD/_REMOVE, not
    # optional — confirmed against Oracle's own "Details for IAM with
    # Identity Domains" permissions table, which lists CreateSecretKey
    # as requiring "USER_UPDATE and USER_SECRETKEY_ADD" (an AND, not an
    # OR) and DeleteCustomerSecretKey as "USER_UPDATE and
    # USER_SECRETKEY_REMOVE". Every credential-mutating operation in
    # that table follows this same pattern — the specific permission
    # alone is never sufficient. Omitting USER_UPDATE is what caused a
    # live 404 "NotAuthorizedOrNotFound" on CreateCustomerSecretKey.
    #
    # Side effect worth being honest about: USER_UPDATE by itself also
    # covers plain UpdateUser (renaming/redescribing a user) — nothing
    # more dangerous (not USER_UNBLOCK, not USER_DELETE, not password
    # reset, those are separate permissions not granted here), but it
    # is a real capability beyond pure secret-key management that comes
    # bundled in because OCI requires it as a co-permission for every
    # per-user credential mutation. Still tenancy-wide across all
    # users, not scoped to just the two homelab-cloud-sync-* ones — see
    # docs/cloud-credential-creation.md for why.
    statement_list = [
        f"Allow group id {group['id']} to manage users in tenancy "
        "where any {request.permission='USER_UPDATE', "
        "request.permission='USER_SECRETKEY_ADD', "
        "request.permission='USER_SECRETKEY_REMOVE'}"
    ]
    try:
        post(
            "/20160918/policies",
            {
                "compartmentId": tenancy,
                "name": name,
                "description": "Scopes homelab-key-rotation to add/remove customer secret keys only",
                "statements": statement_list,
            },
        )
    except requests.HTTPError as exc:
        if exc.response.status_code != 409:
            raise
        # Update, not skip: an existing policy here might be the
        # pre-fix version (missing USER_UPDATE, as this tenancy's was)
        # — leaving it in place on 409 would silently keep the broken
        # grant forever. UpdatePolicy's PUT with a bare
        # {"statements": [...]} body is confirmed live: it applies
        # immediately (a raw re-GET right after reflects it), though
        # the OCI Console's own policy detail view can lag behind that
        # by a short, inconsistent delay — don't trust the Console
        # alone when verifying this against a real tenancy.
        print(f"oci: policy {name} already exists, updating its statements", file=sys.stderr)
        existing = oci_lookup_one(session, endpoint, tenancy, "policies", name)
        put(f"/20160918/policies/{existing['id']}", {"statements": statement_list})

    return user["id"]


def create_oci_rotation_key(admin_email: str) -> None:
    rotation_files = [
        "_rotation-key-oci-user-ocid",
        "_rotation-key-oci-fingerprint",
        "_rotation-key-oci-private-key.pem",
        "_rotation-key-oci-tenancy-ocid",
        "_rotation-key-oci-region",
    ]
    keypair_cached = all(cached(f) for f in rotation_files)

    signer, endpoint, tenancy, region = oci_master_auth_and_endpoint()
    session = requests.Session()
    session.auth = signer
    session.headers["Content-Type"] = "application/json"

    def post(path: str, body: dict) -> dict:
        resp = session.post(f"{endpoint}{path}", json=body)
        resp.raise_for_status()
        return resp.json()

    def put(path: str, body: dict) -> dict:
        resp = session.put(f"{endpoint}{path}", json=body)
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    # OBJECT_OVERWRITE is required alongside OBJECT_CREATE for multipart
    # uploads specifically (Oracle's own multipart-uploads doc states this
    # as a named requirement beyond a normal write policy) — without it,
    # CreateMultipartUpload 404s as NoSuchBucket like any other
    # unauthorized-vs-missing case on this API, even though OBJECT_CREATE
    # alone is sufficient for a single-part PutObject. No OBJECT_DELETE on
    # either leaf — OBJECT_OVERWRITE lets the write leaf replace an existing
    # object's content but still can't remove one.
    oci_ensure_leaf_identity(
        session,
        endpoint,
        post,
        put,
        tenancy,
        "write",
        ["OBJECT_INSPECT", "OBJECT_CREATE", "OBJECT_OVERWRITE"],
        admin_email,
    )
    oci_ensure_leaf_identity(
        session,
        endpoint,
        post,
        put,
        tenancy,
        "read",
        ["OBJECT_INSPECT", "OBJECT_READ"],
        admin_email,
    )

    rotation_user_id = oci_ensure_rotation_identity(session, endpoint, post, put, tenancy, admin_email)

    if keypair_cached:
        cached_user_id = read_cache("_rotation-key-oci-user-ocid")
        if rotation_user_id != cached_user_id:
            # The lookup-by-name above found a different user OCID than the one
            # the cached keypair was issued for — that keypair no longer
            # belongs to "homelab-key-rotation" and won't authenticate as it.
            print(
                f"oci: cached rotation keypair is for user {cached_user_id}, but "
                f"'homelab-key-rotation' now resolves to {rotation_user_id} — "
                "delete the _rotation-key-oci-* cache files and re-run to fix",
                file=sys.stderr,
            )
            sys.exit(1)
        print("oci: rotation keypair already cached (unchanged); leaf + rotation policies re-verified above")
        return

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )

    # "key" is confirmed, not a guess — Oracle's Python SDK model
    # reference (CreateApiKeyDetails) documents it as the sole required
    # field, generated directly from their API spec. The fingerprint
    # comes back computed in the response; we don't need to derive it.
    api_key = post(f"/20160918/users/{rotation_user_id}/apiKeys", {"key": public_pem})

    write_cache("_rotation-key-oci-user-ocid", rotation_user_id)
    write_cache("_rotation-key-oci-fingerprint", api_key["fingerprint"])
    write_cache("_rotation-key-oci-private-key.pem", private_pem)
    write_cache("_rotation-key-oci-tenancy-ocid", tenancy)
    write_cache("_rotation-key-oci-region", region)
    print("oci: rotation identity and leaf users cached")
