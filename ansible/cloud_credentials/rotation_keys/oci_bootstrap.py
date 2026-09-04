"""OCI leaf-identity bootstrap (classic IAM: users/groups/policies for
the two cloud_sync leaves) and rotation-credential bootstrap (a
Confidential Application's OAuth2 client credentials - see ADR 0016).
These are two unrelated auth models sharing this module only because
create_rotation_keys.py's --provider oci wires up both in one pass.
"""

from __future__ import annotations

import getpass
import sys

import requests

from cloud_credentials.cache import cached, read_cache, require_cache_file, write_cache
from cloud_credentials.expiry import utcnow_iso
from cloud_credentials.rotation_keys.oci_iam import (
    oci_get_or_create_group,
    oci_get_or_create_user,
    oci_lookup_one,
    oci_master_auth_and_endpoint,
)
from cloud_credentials.rotation_keys.oci_scim import oci_scim_access_token, oci_scim_domain_and_credentials

# Must match leaf_keys/oci.py's OCI_BUCKET exactly - both flows operate
# on the same bucket, one scoping IAM policies to it, the other reading/
# writing objects in it. A drift here would silently policy-scope one
# bucket while cloud_sync/restore_discovery actually use another.
OCI_BUCKET = "homelab-backups"

# The Confidential Application is registered by hand in Console under
# exactly this name (see docs/cloud-credential-creation.md) - there is
# no API path here to create one. Automating Confidential Application
# registration + OAuth configuration + app role grant + activation is a
# materially larger, unverified surface than prompting once for values
# a human already has in front of them (same trade-off R2's rotation
# token makes - see rotation_keys/r2.py).
OCI_SCIM_APP_DISPLAY_NAME = "homelab-oci-scim-rotation"

# Confirmed live against this tenancy - not spelled out anywhere in
# Oracle's own docs pages (unlike customerSecretKey's schema URN,
# which is), but follows the same
# urn:ietf:params:scim:schemas:oracle:idcs:<ResourceName> pattern.
APP_CLIENT_SECRET_REGENERATOR_SCHEMA = "urn:ietf:params:scim:schemas:oracle:idcs:AppClientSecretRegenerator"  # noqa: S105 - a schema URN, not a credential


def oci_ensure_leaf_identity(session, endpoint, post, put, tenancy: str, leaf: str, permissions: list[str], admin_email: str) -> str:
    """Create the leaf's IAM user/group if missing, and always (re-)verify its
    policy statement matches `permissions`; return its user OCID.

    The user/group/membership steps are skipped once `cache_key` exists —
    those never change after creation. The policy step is NOT gated by that
    cache: it 409-and-updates every run, so a permissions-list change here
    (e.g. adding OBJECT_OVERWRITE) actually reaches an already-bootstrapped
    tenancy on the next run, instead of being silently skipped forever.
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


def _prompt_oci_scim_app_credentials() -> tuple[str, str, str]:
    print(
        f"OCI Identity Domains Confidential Application — register "
        f"'{OCI_SCIM_APP_DISPLAY_NAME}' by hand in Console (Identity & "
        "Security > Domains > your domain > Integrated Applications > "
        "Add > Confidential Application): enable the 'Client "
        "credentials' grant, grant the 'User Administrator' app role "
        "(confirmed sufficient for both CustomerSecretKeys and this "
        "app's own secret regeneration — see "
        "docs/cloud-credential-creation.md), skip Web Tier Policy, and "
        "Activate it. Domain URL and Client ID aren't secret; Client "
        "Secret input is hidden and cached after this:"
    )
    domain_url = input("Domain URL (e.g. https://idcs-xxxx.identity.oraclecloud.com): ").strip().rstrip("/")
    client_id = input("Client ID: ").strip()
    client_secret = getpass.getpass("Client Secret (hidden): ")
    return domain_url, client_id, client_secret


def _find_app_id(session: requests.Session, domain_url: str, display_name: str) -> str:
    resp = session.get(f"{domain_url}/admin/v1/Apps", params={"filter": f'displayName eq "{display_name}"'})
    resp.raise_for_status()
    resources = resp.json().get("Resources", [])
    if not resources:
        raise RuntimeError(
            f"no Confidential Application found with displayName={display_name!r} - register it in Console first, see docs/cloud-credential-creation.md"
        )
    return resources[0]["id"]


def _oci_ensure_scim_app_credentials() -> None:
    """Idempotent: skips prompting entirely once all four cache files
    exist. Verifies the credentials actually work (a token exchange)
    before caching anything, so a typo doesn't silently get cached as
    if it were good."""
    cache_keys = ["_rotation-key-oci-domain-url", "_rotation-key-oci-client-id", "_rotation-key-oci-client-secret", "_rotation-key-oci-app-id"]
    if all(cached(k) for k in cache_keys):
        print("oci: SCIM app credentials already cached, skipping")
        return

    domain_url, client_id, client_secret = _prompt_oci_scim_app_credentials()
    token = oci_scim_access_token(domain_url, client_id, client_secret)
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    session.headers["Content-Type"] = "application/scim+json"
    app_id = _find_app_id(session, domain_url, OCI_SCIM_APP_DISPLAY_NAME)

    write_cache("_rotation-key-oci-domain-url", domain_url)
    write_cache("_rotation-key-oci-client-id", client_id)
    write_cache("_rotation-key-oci-client-secret", client_secret)
    write_cache("_rotation-key-oci-app-id", app_id)
    # Self-tracked, not native (see ADR 0016's Context: the App
    # resource has no expires_on field of its own).
    write_cache("_rotation-key-oci-created-at", utcnow_iso())
    print("oci: SCIM app credentials verified and cached")


def create_oci_rotation_key(admin_email: str) -> None:
    signer, endpoint, tenancy, _region = oci_master_auth_and_endpoint()
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

    _oci_ensure_scim_app_credentials()


def rotate_oci_rotation_key(admin_email: str) -> bool:
    """Re-verifies leaf policies (cheap, idempotent, worth confirming at
    rotation time - same rationale as before), then regenerates the
    Confidential Application's own client secret.

    Unlike leaf-key rotation (leaf_keys/oci.py:rotate_oci) there is no
    verify-then-revoke available here: OCI supports exactly one active
    secret per App, and regenerating invalidates the old one
    immediately (see ADR 0016). The new secret is cached as soon as
    it's returned, before verification - the OLD secret is already
    gone regardless of whether the verification round-trip below
    succeeds, so withholding the cache write on a verification failure
    would only throw away the one copy of a value OCI shows exactly
    once, for no benefit.
    """
    signer, endpoint, tenancy, _region = oci_master_auth_and_endpoint()
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

    oci_ensure_leaf_identity(session, endpoint, post, put, tenancy, "write", ["OBJECT_INSPECT", "OBJECT_CREATE", "OBJECT_OVERWRITE"], admin_email)
    oci_ensure_leaf_identity(session, endpoint, post, put, tenancy, "read", ["OBJECT_INSPECT", "OBJECT_READ"], admin_email)

    domain_url, client_id, old_secret = oci_scim_domain_and_credentials()
    app_id = require_cache_file("_rotation-key-oci-app-id", "Run: python3 -m cloud_credentials.create_rotation_keys --provider oci")

    try:
        old_token = oci_scim_access_token(domain_url, client_id, old_secret)
    except (requests.HTTPError, requests.RequestException, KeyError) as exc:
        print(
            f"oci: authenticating with the current cached secret failed ({exc}) — "
            "can't safely regenerate without a working session first. Fix the "
            "cached secret by hand (Console's Regenerate button) before retrying.",
            file=sys.stderr,
        )
        return False

    scim_session = requests.Session()
    scim_session.headers["Authorization"] = f"Bearer {old_token}"
    scim_session.headers["Content-Type"] = "application/scim+json"

    regen_resp = scim_session.post(
        f"{domain_url}/admin/v1/AppClientSecretRegenerator", json={"schemas": [APP_CLIENT_SECRET_REGENERATOR_SCHEMA], "appId": app_id}
    )
    if regen_resp.status_code not in (200, 201):
        print(
            f"oci: regenerating the app's client secret failed ({regen_resp.status_code} {regen_resp.text}) "
            "— the OLD secret is untouched, nothing was invalidated.",
            file=sys.stderr,
        )
        return False

    new_secret = regen_resp.json().get("clientSecret")
    if not new_secret:
        print(
            "oci: regenerate succeeded but returned no clientSecret — the OLD "
            "secret is now invalid and there's nothing to fall back to. Use "
            "Console's own Regenerate button now.",
            file=sys.stderr,
        )
        return False

    write_cache("_rotation-key-oci-client-secret", new_secret)
    write_cache("_rotation-key-oci-created-at", utcnow_iso())

    try:
        oci_scim_access_token(domain_url, client_id, new_secret)
    except (requests.HTTPError, requests.RequestException, KeyError) as exc:
        print(
            f"oci: new secret is cached, but verifying it with a fresh token "
            f"exchange failed ({exc}). The OLD secret is already invalidated "
            "regardless — check the cached value by hand.",
            file=sys.stderr,
        )
        return False

    print("oci: rotation credential (Confidential Application client secret) regenerated and verified")
    return True
