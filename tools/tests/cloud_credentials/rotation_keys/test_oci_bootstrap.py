"""Unit tests for cloud_credentials.rotation_keys.oci_bootstrap.

Run via `uv run pytest tools/tests/ -v`. Every HTTP call is mocked;
nothing here talks to a real tenancy or registers/regenerates a real
Confidential Application.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from _responses import response
from cloud_credentials.rotation_keys import oci_bootstrap


def seed_scim_app_credentials(rotation_vault):
    rotation_vault.seed("_rotation-key-oci-domain-url", "https://idcs-example.identity.oraclecloud.com")
    rotation_vault.seed("_rotation-key-oci-client-id", "client-123")
    rotation_vault.seed("_rotation-key-oci-client-secret", "OLD_SECRET")
    rotation_vault.seed("_rotation-key-oci-app-id", "app-1")


class TestCreateOciRotationKey:
    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "_oci_ensure_scim_app_credentials")
    @pytest.mark.usefixtures("fake_vault")
    def test_ensures_both_leaf_identities_and_scim_credentials(self, mock_ensure_scim, mock_ensure_leaf, mock_auth):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")

        oci_bootstrap.create_oci_rotation_key(admin_email="you@example.com")

        assert mock_ensure_leaf.call_count == 2
        leaves_seen = {call.args[5] for call in mock_ensure_leaf.call_args_list}
        assert leaves_seen == {"write", "read"}
        mock_ensure_scim.assert_called_once()

    @patch.object(oci_bootstrap, "oci_scim_access_token", return_value="tok")
    def test_scim_credentials_already_cached_skips_prompting(self, mock_token, rotation_vault, capsys):
        seed_scim_app_credentials(rotation_vault)
        with patch.object(oci_bootstrap, "input") as mock_input:
            oci_bootstrap._oci_ensure_scim_app_credentials()
        mock_input.assert_not_called()
        mock_token.assert_not_called()
        assert "already cached, skipping" in capsys.readouterr().out
        assert rotation_vault.get("_rotation-key-oci-client-secret") == "OLD_SECRET"

    @patch.object(oci_bootstrap, "identity_domains_client_for_token")
    @patch.object(oci_bootstrap, "oci_scim_access_token", return_value="tok")
    def test_first_run_prompts_verifies_and_caches(self, mock_token, mock_client_factory, rotation_vault):
        client = mock_client_factory.return_value
        client.list_apps.return_value = MagicMock(data=MagicMock(resources=[MagicMock(id="app-1")]))

        with (
            patch.object(oci_bootstrap, "input", side_effect=["https://idcs-example.identity.oraclecloud.com/", "client-123"]),
            patch("getpass.getpass", return_value="the-secret"),
        ):
            oci_bootstrap._oci_ensure_scim_app_credentials()

        # Trailing slash stripped, matching oci_scim.py's own convention.
        assert rotation_vault.get("_rotation-key-oci-domain-url") == "https://idcs-example.identity.oraclecloud.com"
        assert rotation_vault.get("_rotation-key-oci-client-id") == "client-123"
        assert rotation_vault.get("_rotation-key-oci-client-secret") == "the-secret"
        assert rotation_vault.get("_rotation-key-oci-app-id") == "app-1"
        assert rotation_vault.get("_rotation-key-oci-created-at") is not None
        mock_client_factory.assert_called_once_with("https://idcs-example.identity.oraclecloud.com", "tok")

    @patch.object(oci_bootstrap, "identity_domains_client_for_token")
    @patch.object(oci_bootstrap, "oci_scim_access_token", return_value="tok")
    def test_app_not_found_raises_before_caching_anything(self, mock_token, mock_client_factory, rotation_vault):
        client = mock_client_factory.return_value
        client.list_apps.return_value = MagicMock(data=MagicMock(resources=[]))

        with (
            patch.object(oci_bootstrap, "input", side_effect=["https://idcs-example.identity.oraclecloud.com", "client-123"]),
            patch("getpass.getpass", return_value="the-secret"),
            pytest.raises(RuntimeError),
        ):
            oci_bootstrap._oci_ensure_scim_app_credentials()

        assert rotation_vault.get("_rotation-key-oci-domain-url") is None


class TestRotateOciRotationKey:
    @pytest.fixture(autouse=True)
    def _seeded(self, rotation_vault):
        seed_scim_app_credentials(rotation_vault)

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_scim_access_token")
    def test_reverifies_leaf_identities_before_touching_the_secret(self, mock_token, mock_ensure_leaf, mock_auth, session_class):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_token.side_effect = ["old-tok", "new-tok"]
        session = session_class.return_value
        session.post.return_value = response(201, {"clientSecret": "NEW_SECRET"})

        oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        assert mock_ensure_leaf.call_count == 2

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_scim_access_token", side_effect=oci_bootstrap.requests.HTTPError("401 invalid_client"))
    def test_old_secret_auth_failure_stops_before_any_regenerate_call(self, mock_token, mock_ensure_leaf, mock_auth, rotation_vault):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")

        ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        assert not ok
        assert rotation_vault.get("_rotation-key-oci-client-secret") == "OLD_SECRET"

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_scim_access_token", return_value="old-tok")
    def test_regenerate_failure_leaves_old_secret_untouched(self, mock_token, mock_ensure_leaf, mock_auth, rotation_vault, session_class):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        session = session_class.return_value
        session.post.return_value = response(403, text="insufficient_scope")

        ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        assert not ok
        assert rotation_vault.get("_rotation-key-oci-client-secret") == "OLD_SECRET"

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_scim_access_token")
    def test_verification_failure_still_caches_the_new_secret(self, mock_token, mock_ensure_leaf, mock_auth, rotation_vault, session_class):
        """The safety property that matters most here: once regenerate
        succeeds, the OLD secret is already gone - a failed verification
        round-trip must not throw away the only copy of the new one."""
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_token.side_effect = ["old-tok", oci_bootstrap.requests.HTTPError("network blip")]
        session = session_class.return_value
        session.post.return_value = response(201, {"clientSecret": "NEW_SECRET"})

        ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        assert not ok
        assert rotation_vault.get("_rotation-key-oci-client-secret") == "NEW_SECRET"

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_scim_access_token")
    def test_full_success_caches_new_secret_and_updates_timestamp(self, mock_token, mock_ensure_leaf, mock_auth, rotation_vault, session_class):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_token.side_effect = ["old-tok", "new-tok"]
        session = session_class.return_value
        session.post.return_value = response(201, {"clientSecret": "NEW_SECRET"})
        rotation_vault.seed("_rotation-key-oci-created-at", "2020-01-01T00:00:00+00:00")

        ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        assert ok
        assert rotation_vault.get("_rotation-key-oci-client-secret") == "NEW_SECRET"
        assert rotation_vault.get("_rotation-key-oci-created-at") != "2020-01-01T00:00:00+00:00"
        sent_body = session.post.call_args.kwargs["json"]
        assert sent_body["appId"] == "app-1"
