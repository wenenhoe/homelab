"""Unit tests for openbao_utils.client - the OpenBao/Vault-specific
primitives (KV v2 read/write, AppRole login, the OpenBao URL itself).

Run via `uv run pytest tools/tests/ -v`. Every Vault call is mocked;
nothing here touches a real OpenBao. The generic repo-navigation
helpers this module used to also include (main_domain, fetch_root_cert,
etc.) are tested once, directly, in tools/tests/utils/test_repo.py.
"""

from __future__ import annotations

import hvac
import pytest
from openbao_utils import client


class TestOpenbaoBaseUrl:
    """openbao_base_url() calls utils.repo's own main_domain() internally,
    which reads main-domain from utils.repo.SECRETS_DIR, not anything in
    this module."""

    def test_builds_expected_url(self, secrets_dir):
        secrets_dir.seed("main-domain", "example.com")
        assert client.openbao_base_url() == "https://openbao.sec.lan.example.com:8200"


class TestVaultLogin:
    """Bare login only - no file-reading/validation here, that's each
    caller's own job (see cache.py's/openbao_utils/bootstrap.py's own
    VaultLoginTests for the wrapper behavior)."""

    def test_logs_in_with_the_given_role_and_secret_id(self, hvac_client):
        client.vault_login(hvac_client, "some-role-id", "some-secret-id")

        hvac_client.auth.approle.login.assert_called_once_with(role_id="some-role-id", secret_id="some-secret-id")


class TestVaultReadWrite:
    def test_read_returns_none_on_invalid_path(self, hvac_client):
        hvac_client.secrets.kv.v2.read_secret_version.side_effect = hvac.exceptions.InvalidPath
        assert client.vault_read(hvac_client, "some/path") is None

    def test_read_returns_value_on_success(self, hvac_client):
        hvac_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "the-value"}}}
        assert client.vault_read(hvac_client, "some/path") == "the-value"

    def test_read_uses_the_default_mount_point(self, hvac_client):
        hvac_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        client.vault_read(hvac_client, "some/path")
        hvac_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="some/path",
            mount_point=client.VAULT_KV_MOUNT,
            raise_on_deleted_version=True,
        )

    def test_read_accepts_a_mount_point_override(self, hvac_client):
        hvac_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        client.vault_read(hvac_client, "some/path", mount_point="other-mount")
        _, kwargs = hvac_client.secrets.kv.v2.read_secret_version.call_args
        assert kwargs["mount_point"] == "other-mount"

    def test_read_propagates_non_invalid_path_errors(self, hvac_client):
        hvac_client.secrets.kv.v2.read_secret_version.side_effect = hvac.exceptions.Forbidden
        with pytest.raises(hvac.exceptions.Forbidden):
            client.vault_read(hvac_client, "some/path")

    def test_write_writes_the_correct_payload(self, hvac_client):
        client.vault_write(hvac_client, "some/path", "the-value")
        hvac_client.secrets.kv.v2.create_or_update_secret.assert_called_once_with(
            path="some/path",
            secret={"value": "the-value"},
            mount_point=client.VAULT_KV_MOUNT,
        )

    def test_write_accepts_a_mount_point_override(self, hvac_client):
        client.vault_write(hvac_client, "some/path", "the-value", mount_point="other-mount")
        _, kwargs = hvac_client.secrets.kv.v2.create_or_update_secret.call_args
        assert kwargs["mount_point"] == "other-mount"

    def test_write_propagates_errors(self, hvac_client):
        hvac_client.secrets.kv.v2.create_or_update_secret.side_effect = hvac.exceptions.Forbidden
        with pytest.raises(hvac.exceptions.Forbidden):
            client.vault_write(hvac_client, "some/path", "value")
