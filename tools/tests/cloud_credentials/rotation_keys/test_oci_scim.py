"""Unit tests for cloud_credentials.rotation_keys.oci_scim.

Run via `uv run pytest tools/tests/ -v`. Every HTTP call is mocked;
nothing here talks to a real tenancy.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests
from _responses import response
from cloud_credentials.rotation_keys import oci_scim


class TestOciScim:
    @pytest.fixture(autouse=True)
    def _seeded(self, fake_vault):
        fake_vault.seed("rotation", "_rotation-key-oci-domain-url", "https://idcs-example.identity.oraclecloud.com/")
        fake_vault.seed("rotation", "_rotation-key-oci-client-id", "client-123")
        fake_vault.seed("rotation", "_rotation-key-oci-client-secret", "shh")

    def test_domain_url_trailing_slash_is_stripped(self):
        domain_url, client_id, client_secret = oci_scim.oci_scim_domain_and_credentials()
        assert domain_url == "https://idcs-example.identity.oraclecloud.com"
        assert client_id == "client-123"
        assert client_secret == "shh"

    @patch.object(oci_scim.requests, "post")
    def test_access_token_uses_client_credentials_grant(self, mock_post):
        mock_post.return_value = response(json_body={"access_token": "tok"})
        token = oci_scim.oci_scim_access_token("https://x", "cid", "csec")
        assert token == "tok"
        sent = mock_post.call_args
        assert sent.args[0] == "https://x/oauth2/v1/token"
        assert sent.kwargs["data"] == {"grant_type": "client_credentials", "scope": "urn:opc:idm:__myscopes__"}

    @patch.object(oci_scim.requests, "post")
    def test_session_carries_bearer_token_and_domain_url(self, mock_post):
        mock_post.return_value = response(json_body={"access_token": "tok"})
        session, domain_url = oci_scim.oci_scim_session()
        assert domain_url == "https://idcs-example.identity.oraclecloud.com"
        assert session.headers["Authorization"] == "Bearer tok"

    @patch.object(oci_scim.requests, "post")
    def test_identity_domains_client_targets_the_cached_domain_url(self, mock_post):
        mock_post.return_value = response(json_body={"access_token": "tok"})
        client = oci_scim.oci_identity_domains_client()
        assert client.base_client.endpoint == "https://idcs-example.identity.oraclecloud.com"

    def test_bearer_token_signer_sets_authorization_header_not_oci_signature(self):
        """The one property that matters here: IdentityDomainsClient's
        default Signer does OCI API-key request signing, which this
        SCIM OAuth2 flow has no key for - the custom signer must
        replace that entirely with a plain bearer header, not add to
        whatever the default signer would have done."""
        request = requests.Request(method="POST", url="https://idcs-example.identity.oraclecloud.com/admin/v1/CustomerSecretKeys").prepare()

        signed = oci_scim._BearerTokenSigner("tok")(request)

        assert signed.headers["Authorization"] == "Bearer tok"
        assert signed.headers["Content-Type"] == "application/scim+json"
        assert "Signature" not in signed.headers.get("Authorization", "")
