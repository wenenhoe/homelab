"""Shared OAuth2 client-credentials + Identity Domains SCIM plumbing for
OCI, used by leaf_keys/oci.py, rotation_keys/oci_bootstrap.py, and
check_freshness.py. See ADR 0016 - this is a second, unrelated auth
model to oci_iam.py's classic Signature V1 signer, not a replacement
for it: oci_iam.py stays in use for leaf-identity user/group/policy
bootstrap, which SCIM has no equivalent for.
"""

from __future__ import annotations

import base64

import requests

from cloud_credentials.cache import require_cache_file

SCIM_CUSTOMER_SECRET_KEY_SCHEMA = "urn:ietf:params:scim:schemas:oracle:idcs:customerSecretKey"  # noqa: S105 - a schema URN, not a credential

how_to_get_it_oci_scim = "Run: python3 -m cloud_credentials.create_rotation_keys --provider oci"


def oci_scim_domain_and_credentials() -> tuple[str, str, str]:
    domain_url = require_cache_file("_rotation-key-oci-domain-url", how_to_get_it_oci_scim).rstrip("/")
    client_id = require_cache_file("_rotation-key-oci-client-id", how_to_get_it_oci_scim)
    client_secret = require_cache_file("_rotation-key-oci-client-secret", how_to_get_it_oci_scim)
    return domain_url, client_id, client_secret


def oci_scim_access_token(domain_url: str, client_id: str, client_secret: str) -> str:
    # grant_type=client_credentials, scope=urn:opc:idm:__myscopes__ -
    # confirmed against Oracle's own REST API and IAM getting-started
    # docs, and live against this tenancy - see
    # cloud_credentials/spikes/oci_scim_oauth_check.py, which this
    # mirrors exactly.
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = requests.post(
        f"{domain_url}/oauth2/v1/token",
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        data={"grant_type": "client_credentials", "scope": "urn:opc:idm:__myscopes__"},
        timeout=45,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def oci_scim_session() -> tuple[requests.Session, str]:
    """A ready-to-use SCIM session (Bearer token already set) and the
    domain_url to call it against. Fetches a fresh access token on
    every call - these are short, one-shot scripts, not a long-running
    service, and the token itself is never cached (see ADR 0016: only
    the client ID + secret is the long-lived credential here)."""
    domain_url, client_id, client_secret = oci_scim_domain_and_credentials()
    token = oci_scim_access_token(domain_url, client_id, client_secret)
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    session.headers["Content-Type"] = "application/scim+json"
    return session, domain_url
