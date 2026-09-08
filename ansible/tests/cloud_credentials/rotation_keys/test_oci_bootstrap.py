"""Unit tests for cloud_credentials.rotation_keys.oci_bootstrap.

Run via `uv run pytest ansible/tests/ -v`. Every HTTP call is mocked;
nothing here talks to a real tenancy or registers/regenerates a real
Confidential Application.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _fake_vault import FakeVaultTestCase
from cloud_credentials.rotation_keys import oci_bootstrap


def _mock_response(status_code: int, json_body: dict | None = None, text: str = ""):
    resp = MagicMock(status_code=status_code, text=text or str(json_body))
    resp.json.return_value = json_body or {}
    resp.raise_for_status = MagicMock() if status_code < 400 else MagicMock(side_effect=Exception(f"{status_code} {text}"))
    return resp


class OciBootstrapTestBase(FakeVaultTestCase):
    def seed(self, name: str, value: str) -> None:
        self.vault_seed("rotation", name, value)

    def get(self, name: str) -> str | None:
        return self.vault_get("rotation", name)

    def seed_scim_app_credentials(self):
        self.seed("_rotation-key-oci-domain-url", "https://idcs-example.identity.oraclecloud.com")
        self.seed("_rotation-key-oci-client-id", "client-123")
        self.seed("_rotation-key-oci-client-secret", "OLD_SECRET")
        self.seed("_rotation-key-oci-app-id", "app-1")


class CreateOciRotationKeyTests(OciBootstrapTestBase):
    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "_oci_ensure_scim_app_credentials")
    def test_ensures_both_leaf_identities_and_scim_credentials(self, mock_ensure_scim, mock_ensure_leaf, mock_auth):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")

        oci_bootstrap.create_oci_rotation_key(admin_email="you@example.com")

        self.assertEqual(mock_ensure_leaf.call_count, 2)
        leaves_seen = {call.args[5] for call in mock_ensure_leaf.call_args_list}
        self.assertEqual(leaves_seen, {"write", "read"})
        mock_ensure_scim.assert_called_once()

    @patch.object(oci_bootstrap, "oci_scim_access_token", return_value="tok")
    def test_scim_credentials_already_cached_skips_prompting(self, mock_token):
        self.seed_scim_app_credentials()
        with patch.object(oci_bootstrap, "input") as mock_input:
            oci_bootstrap._oci_ensure_scim_app_credentials()
        mock_input.assert_not_called()
        mock_token.assert_not_called()

    @patch.object(oci_bootstrap.requests, "Session")
    @patch.object(oci_bootstrap, "oci_scim_access_token", return_value="tok")
    def test_first_run_prompts_verifies_and_caches(self, mock_token, mock_session_cls):
        session = mock_session_cls.return_value
        session.get.return_value = _mock_response(200, {"Resources": [{"id": "app-1"}]})

        with (
            patch.object(oci_bootstrap, "input", side_effect=["https://idcs-example.identity.oraclecloud.com/", "client-123"]),
            patch("getpass.getpass", return_value="the-secret"),
        ):
            oci_bootstrap._oci_ensure_scim_app_credentials()

        # Trailing slash stripped, matching oci_scim.py's own convention.
        self.assertEqual(self.get("_rotation-key-oci-domain-url"), "https://idcs-example.identity.oraclecloud.com")
        self.assertEqual(self.get("_rotation-key-oci-client-id"), "client-123")
        self.assertEqual(self.get("_rotation-key-oci-client-secret"), "the-secret")
        self.assertEqual(self.get("_rotation-key-oci-app-id"), "app-1")
        self.assertIsNotNone(self.get("_rotation-key-oci-created-at"))

    @patch.object(oci_bootstrap.requests, "Session")
    @patch.object(oci_bootstrap, "oci_scim_access_token", return_value="tok")
    def test_app_not_found_raises_before_caching_anything(self, mock_token, mock_session_cls):
        session = mock_session_cls.return_value
        session.get.return_value = _mock_response(200, {"Resources": []})

        with (
            patch.object(oci_bootstrap, "input", side_effect=["https://idcs-example.identity.oraclecloud.com", "client-123"]),
            patch("getpass.getpass", return_value="the-secret"),
            self.assertRaises(RuntimeError),
        ):
            oci_bootstrap._oci_ensure_scim_app_credentials()

        self.assertIsNone(self.get("_rotation-key-oci-domain-url"))


class RotateOciRotationKeyTests(OciBootstrapTestBase):
    def setUp(self):
        super().setUp()
        self.seed_scim_app_credentials()

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_scim_access_token")
    @patch.object(oci_bootstrap.requests, "Session")
    def test_reverifies_leaf_identities_before_touching_the_secret(self, mock_session_cls, mock_token, mock_ensure_leaf, mock_auth):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_token.side_effect = ["old-tok", "new-tok"]
        session = mock_session_cls.return_value
        session.post.return_value = _mock_response(201, {"clientSecret": "NEW_SECRET"})

        oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        self.assertEqual(mock_ensure_leaf.call_count, 2)

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_scim_access_token", side_effect=oci_bootstrap.requests.HTTPError("401 invalid_client"))
    def test_old_secret_auth_failure_stops_before_any_regenerate_call(self, mock_token, mock_ensure_leaf, mock_auth):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")

        ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        self.assertFalse(ok)
        self.assertEqual(self.get("_rotation-key-oci-client-secret"), "OLD_SECRET")

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_scim_access_token", return_value="old-tok")
    @patch.object(oci_bootstrap.requests, "Session")
    def test_regenerate_failure_leaves_old_secret_untouched(self, mock_session_cls, mock_token, mock_ensure_leaf, mock_auth):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        session = mock_session_cls.return_value
        session.post.return_value = _mock_response(403, text="insufficient_scope")

        ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        self.assertFalse(ok)
        self.assertEqual(self.get("_rotation-key-oci-client-secret"), "OLD_SECRET")

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_scim_access_token")
    @patch.object(oci_bootstrap.requests, "Session")
    def test_verification_failure_still_caches_the_new_secret(self, mock_session_cls, mock_token, mock_ensure_leaf, mock_auth):
        """The safety property that matters most here: once regenerate
        succeeds, the OLD secret is already gone - a failed verification
        round-trip must not throw away the only copy of the new one."""
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_token.side_effect = ["old-tok", oci_bootstrap.requests.HTTPError("network blip")]
        session = mock_session_cls.return_value
        session.post.return_value = _mock_response(201, {"clientSecret": "NEW_SECRET"})

        ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        self.assertFalse(ok)
        self.assertEqual(self.get("_rotation-key-oci-client-secret"), "NEW_SECRET")

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_scim_access_token")
    @patch.object(oci_bootstrap.requests, "Session")
    def test_full_success_caches_new_secret_and_updates_timestamp(self, mock_session_cls, mock_token, mock_ensure_leaf, mock_auth):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_token.side_effect = ["old-tok", "new-tok"]
        session = mock_session_cls.return_value
        session.post.return_value = _mock_response(201, {"clientSecret": "NEW_SECRET"})
        self.seed("_rotation-key-oci-created-at", "2020-01-01T00:00:00+00:00")

        ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        self.assertTrue(ok)
        self.assertEqual(self.get("_rotation-key-oci-client-secret"), "NEW_SECRET")
        self.assertNotEqual(self.get("_rotation-key-oci-created-at"), "2020-01-01T00:00:00+00:00")
        sent_body = session.post.call_args.kwargs["json"]
        self.assertEqual(sent_body["appId"], "app-1")


if __name__ == "__main__":
    import unittest

    unittest.main()
