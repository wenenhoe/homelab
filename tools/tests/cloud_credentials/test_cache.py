"""Unit tests for cloud_credentials.cache.

Run via `uv run pytest tools/tests/ -v`. Every SSH/Vault call is
mocked; nothing here touches a real `security` host or a real OpenBao.
Only tests cache.py's own remaining logic (the leaf/rotation Vault-path
taxonomy and scoped()'s session-caching convenience) - the generic
primitives it calls into (fetch_root_cert, vault_login, vault_read,
vault_write) are tested once, directly, in
tools/tests/openbao_utils/test_client.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import create_autospec, patch

import hvac
import pytest
from cloud_credentials import cache
from openbao_utils import client as openbao_utils_module


@pytest.fixture
def secrets_dir(secrets_dir, monkeypatch):
    """The shared fixture patches utils.repo's own SECRETS_DIR - main-domain and the
    controller AppRole credential are always read from there, regardless of which Vault
    path is under test; cache.py has no local reference to it. This also resets the
    process-lifetime session singleton, since it would otherwise leak a mocked
    client/ca_path across tests that don't expect one.
    """
    monkeypatch.setattr(cache, "_session", None)
    return secrets_dir


class TestVaultLogin:
    """cache._vault_login is just the role_id/secret_id file-reading
    and validation wrapper around the shared bare vault_login - see
    tools/tests/openbao_utils/test_client.py for the login call
    itself."""

    @pytest.mark.parametrize(
        "present",
        [
            pytest.param("openbao-controller-secret-id", id="role-id-missing"),
            pytest.param("openbao-controller-role-id", id="secret-id-missing"),
        ],
    )
    def test_exits_1_without_logging_in_when_a_credential_is_missing(self, secrets_dir, hvac_client, capsys, present):
        secrets_dir.seed(present, "some-value")
        with pytest.raises(SystemExit) as exc:
            cache._vault_login(hvac_client)

        assert exc.value.code == 1
        assert "openbao-controller-role-id/-secret-id aren't set yet" in capsys.readouterr().err
        hvac_client.auth.approle.login.assert_not_called()

    @patch("cloud_credentials.cache._bare_vault_login", autospec=True)
    def test_calls_bare_login_with_role_id_and_secret_id(self, mock_bare_login, secrets_dir, hvac_client):
        secrets_dir.seed("openbao-controller-role-id", "some-role-id")
        secrets_dir.seed("openbao-controller-secret-id", "some-secret-id")
        cache._vault_login(hvac_client)

        mock_bare_login.assert_called_once_with(hvac_client, "some-role-id", "some-secret-id")


class TestGetSession:
    @pytest.fixture(autouse=True)
    def _session_environment(self, secrets_dir, monkeypatch):
        secrets_dir.seed("main-domain", "example.com")
        secrets_dir.seed("openbao-controller-role-id", "some-role-id")
        secrets_dir.seed("openbao-controller-secret-id", "some-secret-id")
        monkeypatch.setattr(cache, "fetch_root_cert", create_autospec(cache.fetch_root_cert, return_value="fake-cert"))

    @patch("cloud_credentials.cache.hvac.Client", autospec=True)
    def test_logs_in_only_once_across_multiple_calls(self, mock_client_cls, hvac_client):
        mock_client_cls.return_value = hvac_client
        sessions = [cache._get_session() for _ in range(3)]
        assert sessions[0] is sessions[1] is sessions[2]
        hvac_client.auth.approle.login.assert_called_once()

    @patch("cloud_credentials.cache.hvac.Client", autospec=True)
    def test_session_carries_client_and_ca_path(self, mock_client_cls, hvac_client):
        mock_client_cls.return_value = hvac_client
        session = cache._get_session()
        assert session["client"] is hvac_client
        assert Path(session["ca_path"]).exists()

    @patch("cloud_credentials.cache.hvac.Client", autospec=True)
    def test_client_targets_openbao_and_trusts_only_the_fetched_root_cert(self, mock_client_cls, hvac_client):
        mock_client_cls.return_value = hvac_client
        ca_path = cache._get_session()["ca_path"]

        mock_client_cls.assert_called_once_with(url="https://openbao.sec.lan.example.com:8200", verify=ca_path, timeout=cache.TIMEOUT_SECONDS)
        assert Path(ca_path).read_text() == "fake-cert"

    @patch("cloud_credentials.cache.atexit.register", autospec=True)
    @patch("cloud_credentials.cache.hvac.Client", autospec=True)
    def test_removes_the_root_cert_file_at_process_exit(self, mock_client_cls, mock_register, hvac_client):
        mock_client_cls.return_value = hvac_client
        ca_path = Path(cache._get_session()["ca_path"])
        assert ca_path.exists()

        mock_register.assert_called_once()
        (cleanup,) = mock_register.call_args.args
        cleanup()

        assert not ca_path.exists()


class TestVaultPath:
    def test_builds_leaf_path(self):
        assert cache._vault_path("leaf", "backblaze-b2-write-access-key") == "cloud_credentials/leaf/backblaze-b2-write-access-key"

    def test_builds_rotation_path(self):
        assert cache._vault_path("rotation", "_rotation-key-cloudflare-r2-token") == "cloud_credentials/rotation/_rotation-key-cloudflare-r2-token"

    def test_rejects_unknown_category(self):
        with pytest.raises(ValueError):
            cache._vault_path("bogus", "some-key")


@pytest.fixture
def session_client(secrets_dir, monkeypatch, hvac_client):
    """Bypasses SSH/AppRole login entirely - _vault_read_at/_vault_write_at
    only need a session dict with a usable hvac.Client, however it was
    built."""
    monkeypatch.setattr(cache, "_get_session", create_autospec(cache._get_session, return_value={"client": hvac_client, "ca_path": "/fake/ca.pem"}))
    return hvac_client


class TestScopedReadWrite:
    @pytest.fixture(autouse=True)
    def _scoped(self, session_client):
        self.cached, self.read_cache, self.write_cache, self.require_cache_file = cache.scoped("leaf")

    def test_read_cache_returns_none_on_invalid_path(self, session_client):
        session_client.secrets.kv.v2.read_secret_version.side_effect = hvac.exceptions.InvalidPath
        assert self.read_cache("does-not-exist") is None

    def test_read_cache_returns_value_on_success(self, session_client):
        session_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "the-value"}}}
        assert self.read_cache("some-key") == "the-value"

    def test_read_cache_uses_the_leaf_path_and_mount(self, session_client):
        session_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        self.read_cache("backblaze-b2-write-access-key")
        session_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="cloud_credentials/leaf/backblaze-b2-write-access-key",
            mount_point=openbao_utils_module.VAULT_KV_MOUNT,
            raise_on_deleted_version=True,
        )

    def test_cached_false_on_invalid_path(self, session_client):
        session_client.secrets.kv.v2.read_secret_version.side_effect = hvac.exceptions.InvalidPath
        assert not self.cached("does-not-exist")

    def test_cached_true_on_success(self, session_client):
        session_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        assert self.cached("some-key")

    def test_cached_reads_the_leaf_path_for_the_name(self, session_client):
        session_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        self.cached("some-key")
        session_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="cloud_credentials/leaf/some-key",
            mount_point=openbao_utils_module.VAULT_KV_MOUNT,
            raise_on_deleted_version=True,
        )

    def test_require_cache_file_reads_the_leaf_path_for_the_name(self, session_client):
        session_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        self.require_cache_file("some-key", "unused")
        session_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="cloud_credentials/leaf/some-key",
            mount_point=openbao_utils_module.VAULT_KV_MOUNT,
            raise_on_deleted_version=True,
        )

    def test_write_cache_writes_the_correct_payload(self, session_client):
        self.write_cache("some-key", "the-value")
        session_client.secrets.kv.v2.create_or_update_secret.assert_called_once_with(
            path="cloud_credentials/leaf/some-key",
            secret={"value": "the-value"},
            mount_point=openbao_utils_module.VAULT_KV_MOUNT,
        )

    def test_require_cache_file_exits_1_naming_the_path_and_how_to_get_it_when_missing(self, session_client, capsys):
        session_client.secrets.kv.v2.read_secret_version.side_effect = hvac.exceptions.InvalidPath
        with pytest.raises(SystemExit) as exc:
            self.require_cache_file("missing-key", "run some-command to create it")

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Missing required secret: cloud_credentials/leaf/missing-key" in err
        assert "run some-command to create it" in err

    def test_require_cache_file_returns_value_when_present(self, session_client):
        session_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "present-value"}}}
        assert self.require_cache_file("present-key", "unused") == "present-value"


class TestVaultPathHelper:
    """read_vault_path/write_vault_path - the arbitrary-path escape
    hatch outside the leaf/rotation taxonomy, e.g. hosts/* material."""

    def test_read_vault_path_uses_the_exact_given_path(self, session_client):
        session_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        cache.read_vault_path("hosts/all/telegram/telegram-token")
        session_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="hosts/all/telegram/telegram-token",
            mount_point=openbao_utils_module.VAULT_KV_MOUNT,
            raise_on_deleted_version=True,
        )

    def test_write_vault_path_writes_to_the_exact_given_path(self, session_client):
        cache.write_vault_path("hosts/security/lldap-jwt-secret", "the-value")
        session_client.secrets.kv.v2.create_or_update_secret.assert_called_once_with(
            path="hosts/security/lldap-jwt-secret",
            secret={"value": "the-value"},
            mount_point=openbao_utils_module.VAULT_KV_MOUNT,
        )


class TestScopedRotationCategory:
    """One test confirming scoped("rotation") writes under the other
    top-level path - the leaf-side behavior is already exercised in
    detail by TestScopedReadWrite above, and the two categories only
    differ in which _vault_path prefix gets used."""

    def test_read_cache_uses_the_rotation_path(self, session_client):
        session_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        _, read_cache, _, _ = cache.scoped("rotation")
        read_cache("_rotation-key-cloudflare-r2-token")
        _, kwargs = session_client.secrets.kv.v2.read_secret_version.call_args
        assert kwargs["path"] == "cloud_credentials/rotation/_rotation-key-cloudflare-r2-token"


class TestScopedUnknownCategory:
    def test_raises_on_unknown_category(self):
        with pytest.raises(ValueError):
            cache.scoped("bogus")
