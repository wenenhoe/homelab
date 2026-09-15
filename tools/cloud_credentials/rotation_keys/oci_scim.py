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
from oci.identity_domains import IdentityDomainsClient

from cloud_credentials.cache import scoped

_, _, _, require_cache_file = scoped("rotation")

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
    the client ID + secret is the long-lived credential here).

    Only check_freshness.py uses this now (its single GET-by-scim-id
    call) - leaf_keys/oci.py and oci_bootstrap.py's SCIM calls go
    through oci_identity_domains_client() below instead (Stage 2,
    docs/projects/cloud-credentials-hardening.md). check_freshness.py
    stays on this raw session deliberately - it's out of that stage's
    scope."""
    domain_url, client_id, client_secret = oci_scim_domain_and_credentials()
    token = oci_scim_access_token(domain_url, client_id, client_secret)
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    session.headers["Content-Type"] = "application/scim+json"
    return session, domain_url


class _BearerTokenSigner(requests.auth.AuthBase):
    """Injects the SCIM OAuth2 bearer token in place of request
    signing. IdentityDomainsClient's default `signer` only implements
    OCI's own API-key Signature V1 scheme (oci.signer.Signer) - there
    is no built-in mode for a plain bearer token, so this repo's SCIM
    OAuth2 client-credentials flow (unrelated to that signing scheme)
    needs its own AuthBase implementation, the same extension point
    oci.signer.AbstractBaseSigner itself is built on."""

    def __init__(self, token: str) -> None:
        self._token = token

    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        request.headers["Authorization"] = f"Bearer {self._token}"
        request.headers["Content-Type"] = "application/scim+json"
        return request


# IdentityDomainsClient.__init__ validates `config` (OCID-shaped
# tenancy/user, a fingerprint, an existing key_file) unconditionally,
# even though none of it is read once a custom `signer` replaces the
# default Signer entirely - confirmed by constructing the client this
# way and inspecting the request BaseClient.call_api builds, no live
# call made. Well-formed-but-inert placeholders satisfy that
# validation without asserting a real OCI API-key identity exists.
_INERT_IDENTITY_DOMAINS_CONFIG = {
    "tenancy": "ocid1.tenancy.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "user": "ocid1.user.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "fingerprint": "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00",
    "key_file": "/dev/null",
    "region": "us-ashburn-1",
}


def identity_domains_client_for_token(domain_url: str, token: str) -> IdentityDomainsClient:
    """The lower-level constructor oci_identity_domains_client() below
    wraps - split out for oci_bootstrap.py's _oci_ensure_scim_app_credentials,
    which verifies a domain URL/token pair BEFORE any of it is cached,
    so it can't go through oci_scim_domain_and_credentials()'s
    cache-backed read."""
    return IdentityDomainsClient(config=_INERT_IDENTITY_DOMAINS_CONFIG, service_endpoint=domain_url, signer=_BearerTokenSigner(token))


def oci_identity_domains_client() -> IdentityDomainsClient:
    """A ready-to-use IdentityDomainsClient (SCIM), auth'd the same way
    oci_scim_session() authenticates its requests.Session - a fresh
    OAuth2 client-credentials token on every call, never cached (see
    ADR 0016 and this module's docstring)."""
    domain_url, client_id, client_secret = oci_scim_domain_and_credentials()
    token = oci_scim_access_token(domain_url, client_id, client_secret)
    return identity_domains_client_for_token(domain_url, token)
