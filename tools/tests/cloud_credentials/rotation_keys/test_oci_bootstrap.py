"""Unit tests for cloud_credentials.rotation_keys.oci_bootstrap.

Run via `uv run pytest tools/tests/ -v`. Every HTTP call is mocked;
nothing here talks to a real tenancy or registers/regenerates a real
Confidential Application.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import hvac
import pytest
import requests
from _oci_objects import apps_response
from _responses import response
from cloud_credentials.rotation_keys import oci_bootstrap


def seed_scim_app_credentials(rotation_vault):
    rotation_vault.seed("_rotation-key-oci-domain-url", "https://idcs-example.identity.oraclecloud.com")
    rotation_vault.seed("_rotation-key-oci-client-id", "client-123")
    rotation_vault.seed("_rotation-key-oci-client-secret", "OLD_SECRET")
    rotation_vault.seed("_rotation-key-oci-app-id", "app-1")


class TestCreateOciRotationKey:
    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint", autospec=True)
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity", autospec=True)
    @patch.object(oci_bootstrap, "_oci_ensure_scim_app_credentials", autospec=True)
    @pytest.mark.usefixtures("fake_vault")
    def test_ensures_both_leaf_identities_and_scim_credentials(self, mock_ensure_scim, mock_ensure_leaf, mock_auth):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")

        oci_bootstrap.create_oci_rotation_key(admin_email="you@example.com")

        assert mock_ensure_leaf.call_count == 2
        leaves_seen = {call.args[5] for call in mock_ensure_leaf.call_args_list}
        assert leaves_seen == {"write", "read"}
        mock_ensure_scim.assert_called_once()

    @patch.object(oci_bootstrap, "oci_scim_access_token", return_value="tok", autospec=True)
    def test_scim_credentials_already_cached_skips_prompting(self, mock_token, rotation_vault, capsys):
        seed_scim_app_credentials(rotation_vault)
        with patch("builtins.input", autospec=True) as mock_input:
            oci_bootstrap._oci_ensure_scim_app_credentials()
        mock_input.assert_not_called()
        mock_token.assert_not_called()
        assert "already cached, skipping" in capsys.readouterr().out
        assert rotation_vault.get("_rotation-key-oci-client-secret") == "OLD_SECRET"

    @patch.object(oci_bootstrap, "identity_domains_client_for_token", autospec=True)
    @patch.object(oci_bootstrap, "oci_scim_access_token", return_value="tok", autospec=True)
    def test_first_run_prompts_verifies_and_caches(self, mock_token, mock_client_factory, rotation_vault, identity_domains_client):
        client = mock_client_factory.return_value = identity_domains_client
        client.list_apps.return_value = apps_response("app-1")

        with (
            patch("builtins.input", autospec=True, side_effect=["https://idcs-example.identity.oraclecloud.com/", "client-123"]),
            patch("getpass.getpass", return_value="the-secret", autospec=True),
        ):
            oci_bootstrap._oci_ensure_scim_app_credentials()

        # Trailing slash stripped, matching oci_scim.py's own convention.
        assert rotation_vault.get("_rotation-key-oci-domain-url") == "https://idcs-example.identity.oraclecloud.com"
        assert rotation_vault.get("_rotation-key-oci-client-id") == "client-123"
        assert rotation_vault.get("_rotation-key-oci-client-secret") == "the-secret"
        assert rotation_vault.get("_rotation-key-oci-app-id") == "app-1"
        assert rotation_vault.get("_rotation-key-oci-created-at") is not None
        mock_client_factory.assert_called_once_with("https://idcs-example.identity.oraclecloud.com", "tok")

    @patch.object(oci_bootstrap, "identity_domains_client_for_token", autospec=True)
    @patch.object(oci_bootstrap, "oci_scim_access_token", return_value="tok", autospec=True)
    def test_app_not_found_raises_before_caching_anything(self, mock_token, mock_client_factory, rotation_vault, identity_domains_client):
        client = mock_client_factory.return_value = identity_domains_client
        client.list_apps.return_value = apps_response()

        with (
            patch("builtins.input", autospec=True, side_effect=["https://idcs-example.identity.oraclecloud.com", "client-123"]),
            patch("getpass.getpass", return_value="the-secret", autospec=True),
            pytest.raises(RuntimeError),
        ):
            oci_bootstrap._oci_ensure_scim_app_credentials()

        assert rotation_vault.get("_rotation-key-oci-domain-url") is None


class TestRotateOciRotationKey:
    @pytest.fixture(autouse=True)
    def _seeded(self, rotation_vault):
        seed_scim_app_credentials(rotation_vault)

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint", autospec=True)
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity", autospec=True)
    @patch.object(oci_bootstrap, "oci_scim_access_token", autospec=True)
    def test_reverifies_leaf_identities_before_touching_the_secret(self, mock_token, mock_ensure_leaf, mock_auth, session_class):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_token.side_effect = ["old-tok", "new-tok"]
        order: list[str] = []
        mock_ensure_leaf.side_effect = lambda *args, **kwargs: order.append("ensure_leaf")
        session = session_class.return_value

        def regenerate(*args, **kwargs):
            order.append("regenerate")
            return response(201, {"clientSecret": "NEW_SECRET"})

        session.post.side_effect = regenerate

        oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        assert order == ["ensure_leaf", "ensure_leaf", "regenerate"]

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint", autospec=True)
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity", autospec=True)
    @patch.object(oci_bootstrap, "oci_scim_access_token", side_effect=oci_bootstrap.requests.HTTPError("401 invalid_client"), autospec=True)
    def test_old_secret_auth_failure_stops_before_any_regenerate_call(self, mock_token, mock_ensure_leaf, mock_auth, rotation_vault, session_class):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")

        ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        assert not ok
        session_class.return_value.post.assert_not_called()
        assert rotation_vault.get("_rotation-key-oci-client-secret") == "OLD_SECRET"

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint", autospec=True)
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity", autospec=True)
    @patch.object(oci_bootstrap, "oci_scim_access_token", return_value="old-tok", autospec=True)
    def test_regenerate_failure_leaves_old_secret_untouched(self, mock_token, mock_ensure_leaf, mock_auth, rotation_vault, session_class):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        session = session_class.return_value
        session.post.return_value = response(403, text="insufficient_scope")

        ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        assert not ok
        assert rotation_vault.get("_rotation-key-oci-client-secret") == "OLD_SECRET"

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint", autospec=True)
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity", autospec=True)
    @patch.object(oci_bootstrap, "oci_scim_access_token", autospec=True)
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

    @pytest.mark.parametrize(
        "failure",
        [
            pytest.param(hvac.exceptions.VaultDown("sealed"), id="vault-down"),
            pytest.param(requests.ConnectionError("connection reset"), id="connection-reset"),
        ],
    )
    @patch.object(oci_bootstrap.time, "sleep", autospec=True)
    @patch.object(oci_bootstrap, "write_secret", autospec=True)
    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint", autospec=True)
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity", autospec=True)
    @patch.object(oci_bootstrap, "oci_scim_access_token", autospec=True)
    def test_a_failed_cache_write_is_retried_and_the_rotation_completes(
        self, mock_token, mock_ensure_leaf, mock_auth, mock_write, mock_sleep, failure, session_class
    ):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_token.side_effect = ["old-tok", "new-tok"]
        mock_write.side_effect = [failure, None, None]
        session_class.return_value.post.return_value = response(201, {"clientSecret": "NEW_SECRET"})

        ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        assert ok
        assert mock_write.call_args_list[:2] == [call("_rotation-key-oci-client-secret", "NEW_SECRET")] * 2
        mock_sleep.assert_called_once_with(oci_bootstrap._CACHE_WRITE_RETRY_SECONDS)

    @patch.object(oci_bootstrap.time, "sleep", autospec=True)
    @patch.object(oci_bootstrap, "write_secret", autospec=True)
    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint", autospec=True)
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity", autospec=True)
    @patch.object(oci_bootstrap, "oci_scim_access_token", autospec=True)
    def test_a_timestamp_write_that_never_succeeds_warns_and_still_verifies_the_secret(
        self, mock_token, mock_ensure_leaf, mock_auth, mock_write, mock_sleep, session_class, capsys
    ):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_token.side_effect = ["old-tok", "new-tok"]
        mock_write.side_effect = [None] + [hvac.exceptions.VaultDown("sealed")] * oci_bootstrap._CACHE_WRITE_ATTEMPTS
        session_class.return_value.post.return_value = response(201, {"clientSecret": "NEW_SECRET"})

        ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        assert ok
        assert mock_token.call_count == 2
        err = capsys.readouterr().err
        assert "rotation timestamp could not be cached" in err
        assert "NEW_SECRET" not in err

    @patch.object(oci_bootstrap.time, "sleep", autospec=True)
    @patch.object(oci_bootstrap, "write_secret", autospec=True)
    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint", autospec=True)
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity", autospec=True)
    @patch.object(oci_bootstrap, "oci_scim_access_token", autospec=True)
    def test_a_cache_write_that_never_succeeds_fails_the_rotation_with_recovery_steps(
        self, mock_token, mock_ensure_leaf, mock_auth, mock_write, mock_sleep, session_class, capsys
    ):
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_token.return_value = "old-tok"
        mock_write.side_effect = hvac.exceptions.VaultDown("sealed")
        session_class.return_value.post.return_value = response(201, {"clientSecret": "NEW_SECRET"})

        ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        assert not ok
        assert mock_write.call_args_list == [call("_rotation-key-oci-client-secret", "NEW_SECRET")] * oci_bootstrap._CACHE_WRITE_ATTEMPTS
        assert mock_sleep.call_args_list == [call(oci_bootstrap._CACHE_WRITE_RETRY_SECONDS)] * (oci_bootstrap._CACHE_WRITE_ATTEMPTS - 1)
        mock_token.assert_called_once()
        err = capsys.readouterr().err
        assert "OLD secret is already invalidated" in err
        assert "Regenerate button" in err
        assert "NEW_SECRET" not in err

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint", autospec=True)
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity", autospec=True)
    @patch.object(oci_bootstrap, "oci_scim_access_token", autospec=True)
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
