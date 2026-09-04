"""Unit tests for cloud_credentials.rotation_keys.oci_scim.

Run via `uv run pytest ansible/tests/ -v`. Every HTTP call is mocked;
nothing here talks to a real tenancy.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from cloud_credentials import cache
from cloud_credentials.rotation_keys import oci_scim


class OciScimTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(cache, "SECRETS_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        cache.write_cache("_rotation-key-oci-domain-url", "https://idcs-example.identity.oraclecloud.com/")
        cache.write_cache("_rotation-key-oci-client-id", "client-123")
        cache.write_cache("_rotation-key-oci-client-secret", "shh")

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


if __name__ == "__main__":
    unittest.main()
