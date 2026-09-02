"""Generic OCI IAM helpers shared by both the leaf and rotation identity
bootstrap flows in oci_bootstrap.py: master-identity auth, and
get-or-create/lookup for users and groups.
"""
from __future__ import annotations

import sys

import requests
from oci.config import from_file as oci_config_from_file
from oci.signer import Signer as OCISigner


def oci_master_auth_and_endpoint() -> tuple[OCISigner, str, str, str]:
    # ~/.oci/config is read here, and only here — this is your personal
    # admin identity, used once per rotation-key bootstrap. It's never
    # read by create_leaf_keys.py.
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
