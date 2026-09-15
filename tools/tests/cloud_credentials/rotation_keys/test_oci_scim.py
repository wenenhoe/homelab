"""Unit tests for cloud_credentials.rotation_keys.oci_scim.

Run via `uv run pytest tools/tests/ -v`. Every HTTP call is mocked;
nothing here talks to a real tenancy.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _fake_vault import FakeVaultTestCase
from cloud_credentials.rotation_keys import oci_scim


class OciScimTests(FakeVaultTestCase):
    def setUp(self):
        super().setUp()
        self.vault_seed("rotation", "_rotation-key-oci-domain-url", "https://idcs-example.identity.oraclecloud.com/")
        self.vault_seed("rotation", "_rotation-key-oci-client-id", "client-123")
        self.vault_seed("rotation", "_rotation-key-oci-client-secret", "shh")

    def test_domain_url_trailing_slash_is_stripped(self):
        domain_url, client_id, client_secret = oci_scim.oci_scim_domain_and_credentials()
        self.assertEqual(domain_url, "https://idcs-example.identity.oraclecloud.com")
        self.assertEqual(client_id, "client-123")
        self.assertEqual(client_secret, "shh")

    @patch.object(oci_scim.requests, "post")
    def test_access_token_uses_client_credentials_grant(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=lambda: None, json=lambda: {"access_token": "tok"})
        token = oci_scim.oci_scim_access_token("https://x", "cid", "csec")
        self.assertEqual(token, "tok")
        sent = mock_post.call_args
        self.assertEqual(sent.args[0], "https://x/oauth2/v1/token")
        self.assertEqual(sent.kwargs["data"], {"grant_type": "client_credentials", "scope": "urn:opc:idm:__myscopes__"})

    @patch.object(oci_scim.requests, "post")
    def test_session_carries_bearer_token_and_domain_url(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=lambda: None, json=lambda: {"access_token": "tok"})
        session, domain_url = oci_scim.oci_scim_session()
        self.assertEqual(domain_url, "https://idcs-example.identity.oraclecloud.com")
        self.assertEqual(session.headers["Authorization"], "Bearer tok")

    @patch.object(oci_scim.requests, "post")
    def test_identity_domains_client_targets_the_cached_domain_url(self, mock_post):
        mock_post.return_value = MagicMock(raise_for_status=lambda: None, json=lambda: {"access_token": "tok"})
        client = oci_scim.oci_identity_domains_client()
        self.assertEqual(client.base_client.endpoint, "https://idcs-example.identity.oraclecloud.com")

    def test_bearer_token_signer_sets_authorization_header_not_oci_signature(self):
        """The one property that matters here: IdentityDomainsClient's
        default Signer does OCI API-key request signing, which this
        SCIM OAuth2 flow has no key for - the custom signer must
        replace that entirely with a plain bearer header, not add to
        whatever the default signer would have done."""
        request = requests.Request(method="POST", url="https://idcs-example.identity.oraclecloud.com/admin/v1/CustomerSecretKeys").prepare()

        signed = oci_scim._BearerTokenSigner("tok")(request)

        self.assertEqual(signed.headers["Authorization"], "Bearer tok")
        self.assertEqual(signed.headers["Content-Type"], "application/scim+json")
        self.assertNotIn("Signature", signed.headers.get("Authorization", ""))


if __name__ == "__main__":
    import unittest

    unittest.main()
