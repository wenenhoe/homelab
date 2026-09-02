#!/usr/bin/env python3
"""One-time-per-rotation-key bootstrap: take each provider's master
credential in memory only (never written to disk, never logged) and use
it to mint a narrower "rotation key" that can create/delete the leaf
keys but can't touch backup data itself. ansible/create_cloud_credentials.py
authenticates with the cached rotation key from here on — the master
credential is never read by that script.

R2 has no provider here at all — confirmed live, not an oversight:
Cloudflare rejects granting "manage other tokens" permission to any
token created via the API, so no delegate credential can ever be
minted for R2. Its master token is prompted directly by
create_cloud_credentials.py instead, in memory only, every time it's
actually needed. See docs/cloud-credential-creation.md's R2 section.

See docs/cloud-credential-creation.md for what each remaining
provider's rotation key is actually scoped to (the achievable floor
differs a lot by provider — OCI has real, documented limits on how far
this can be narrowed, not a uniform "create/delete keys only"
guarantee).

Run this again when a rotation key itself needs rotating, or to
re-verify/repair IAM policies (OCI) against an already-cached keypair —
neither regenerates the keypair unless its cache files are missing.
Routine leaf-key rotation is create_cloud_credentials.py's job and
doesn't touch this script or the master credential at all.

Usage:
    python3 ansible/create_rotation_keys.py [--provider {b2,oci,all}]
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

OCI_BUCKET = "homelab-backups"


def cached(name: str) -> bool:
    return (SECRETS_DIR / name).exists()


def write_cache(name: str, value: str) -> None:
    dest = SECRETS_DIR / name
    dest.write_text(value)
    dest.chmod(0o600)


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

    # listKeys/writeKeys/deleteKeys are B2's native "manage other keys"
    # capabilities, independent of writeFiles/readFiles — this key can
    # create and delete application keys but can't read or write file
    # contents itself.
    #
    # No bucketId here — confirmed, not a guess: Backblaze's own docs
    # enumerate every capability a bucket-restricted key is allowed to
    # carry, and listKeys/writeKeys/deleteKeys aren't on that list. Key
    # management is inherently account-wide on B2; a live 400 ("Invalid
    # capability for bucket-level application key") is what surfaced
    # this. This rotation key can create/delete any key on the account,
    # not just ones for homelab-backups-b2 — the actual scoping this key
    # gets is that it holds no file/bucket-data capabilities at all, not
    # that it's bucket-restricted.
    key_resp = session.post(
        f"{api_url}/b2api/v2/b2_create_key",
        json={
            "accountId": account_id,
            "capabilities": ["listKeys", "writeKeys", "deleteKeys", "listBuckets"],
            "keyName": "homelab-cloud-sync-rotation-key",
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


def user_email(admin_email: str, name: str) -> str:
    # +tag addressing off one real mailbox — required because
    # Identity-Domain-enabled OCI tenancies mandate a unique email per
    # user (confirmed via Oracle's own CreateUserDetails docs: "You must
    # provide an email for each user"), even for API-only service
    # identities that will never receive mail. Classic (non-domain)
    # tenancies don't require this at all, so this is a no-op cost for
    # a domain-enabled tenancy and irrelevant for others.
    local, domain = admin_email.split("@", 1)
    return f"{local}+{name}@{domain}"


def oci_lookup_one(session, endpoint, tenancy: str, resource_path: str, name: str) -> dict:
    # OCI's documented List{Users,Groups} shape (GET with
    # compartmentId+name query params) — confirmed live for both users
    # and groups via real 409-then-lookup runs in this tenancy.
    resp = session.get(f"{endpoint}/20160918/{resource_path}", params={"compartmentId": tenancy, "name": name})
    resp.raise_for_status()
    matches = resp.json()
    if len(matches) != 1:
        kind = resource_path[:-1]
        print(f"oci: expected exactly one existing {kind} named {name}, found {len(matches)}", file=sys.stderr)
        sys.exit(1)
    return matches[0]


def oci_get_or_create_user(session, endpoint, post, tenancy: str, name: str, description: str, admin_email: str) -> dict:
    try:
        return post(
            "/20160918/users",
            {
                "compartmentId": tenancy,
                "name": name,
                "description": description,
                "email": user_email(admin_email, name),
            },
        )
    except requests.HTTPError as exc:
        if exc.response.status_code != 409:
            raise
        print(f"oci: user {name} already exists, looking it up instead of recreating it", file=sys.stderr)
        return oci_lookup_one(session, endpoint, tenancy, "users", name)


def oci_get_or_create_group(session, endpoint, post, tenancy: str, name: str, description: str) -> dict:
    try:
        return post("/20160918/groups", {"compartmentId": tenancy, "name": name, "description": description})
    except requests.HTTPError as exc:
        if exc.response.status_code != 409:
            raise
        print(f"oci: group {name} already exists, looking it up instead of recreating it", file=sys.stderr)
        return oci_lookup_one(session, endpoint, tenancy, "groups", name)


def oci_ensure_leaf_identity(
    session, endpoint, post, put, tenancy: str, leaf: str, permissions: list[str], admin_email: str
) -> str:
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
    # "-leaf-" here matches "leaf" terminology throughout - see
    # docs/cloud-credential-creation.md's Rotation section for the
    # one-time file rename this required on an already-provisioned
    # deployment (was "_oci-leg-user-ocid-*" before this rename).
    cache_key = f"_oci-leaf-user-ocid-{leaf}"
    name = f"homelab-cloud-sync-{leaf}"

    if cached(cache_key):
        user_id = (SECRETS_DIR / cache_key).read_text().strip()
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
        group = oci_get_or_create_group(
            session, endpoint, post, tenancy, name, f"Grants {name} its bucket-scoped policy"
        )
        try:
            post("/20160918/userGroupMemberships", {"userId": user["id"], "groupId": group["id"]})
        except requests.HTTPError as exc:
            if exc.response.status_code != 409:
                raise
            print(f"oci: {name} is already a member of its group, skipping", file=sys.stderr)
        user_id = user["id"]

    permission_clause = ", ".join(f"request.permission='{p}'" for p in permissions)
    statement = (
        f"Allow group id {group['id']} to manage objects in tenancy "
        f"where all {{target.bucket.name='{OCI_BUCKET}', any {{{permission_clause}}}}}"
    )
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
        session, endpoint, post, put, tenancy, "write",
        ["OBJECT_INSPECT", "OBJECT_CREATE", "OBJECT_OVERWRITE"], admin_email,
    )
    oci_ensure_leaf_identity(
        session, endpoint, post, put, tenancy, "read",
        ["OBJECT_INSPECT", "OBJECT_READ"], admin_email,
    )

    rotation_user_id = oci_ensure_rotation_identity(session, endpoint, post, put, tenancy, admin_email)

    if keypair_cached:
        cached_user_id = (SECRETS_DIR / "_rotation-key-oci-user-ocid").read_text().strip()
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
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["b2", "oci", "all"], default="all")
    parser.add_argument(
        "--admin-email",
        help=(
            "Required for --provider oci/all. One real mailbox you control — "
            "each OCI service user gets a +tag off it "
            "(you+homelab-cloud-sync-write@domain, etc.), since "
            "Identity-Domain-enabled tenancies require a unique email per user."
        ),
    )
    args = parser.parse_args()

    if args.provider in ("oci", "all") and not args.admin_email:
        parser.error(
            "--admin-email is required for --provider oci (your tenancy's "
            "Identity Domains require a unique email per OCI user)"
        )

    SECRETS_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)

    providers = {
        "b2": create_b2_rotation_key,
        "oci": lambda: create_oci_rotation_key(args.admin_email),
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
