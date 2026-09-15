"""Unit tests for cloud_credentials.cache.

Run via `uv run pytest tools/tests/ -v`. Every SSH/Vault call is
mocked; nothing here touches a real `security` host or a real OpenBao.
Only tests cache.py's own remaining logic (the leaf/rotation Vault-path
taxonomy and scoped()'s session-caching convenience) - the generic
primitives it calls into (fetch_root_cert, vault_login, vault_read,
vault_write) are tested once, directly, in
tools/tests/openbao_client/test_client.py.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import hvac

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cloud_credentials import cache
from openbao_client import client as openbao_client_module


class SecretsDirTestCase(unittest.TestCase):
    """Base for anything touching SECRETS_DIR - main-domain and the
    controller AppRole credential are always read from here, regardless
    of which Vault path is under test. Patches openbao_client.client's
    own SECRETS_DIR, not cache's - cache.py has no local reference to
    it; read_bootstrap_file() (which _vault_login below calls) uses
    the shared module's own copy internally, regardless of who calls
    it. Also resets the process-lifetime session singleton, since it
    would otherwise leak a mocked client/ca_path across tests that
    don't expect one.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        dir_patcher = patch.object(openbao_client_module, "SECRETS_DIR", self.tmp)
        dir_patcher.start()
        self.addCleanup(dir_patcher.stop)
        session_patcher = patch.object(cache, "_session", None)
        session_patcher.start()
        self.addCleanup(session_patcher.stop)

    def seed(self, name: str, value: str) -> None:
        (self.tmp / name).write_text(value)


class VaultLoginTests(SecretsDirTestCase):
    """cache._vault_login is just the role_id/secret_id file-reading
    and validation wrapper around the shared bare vault_login - see
    tools/tests/openbao_client/test_client.py for the login call
    itself."""

    def test_raises_system_exit_when_role_id_missing(self):
        self.seed("openbao-controller-secret-id", "some-secret-id")
        with self.assertRaises(SystemExit):
            cache._vault_login(MagicMock())

    @patch("cloud_credentials.cache._bare_vault_login")
    def test_calls_bare_login_with_role_id_and_secret_id(self, mock_bare_login):
        self.seed("openbao-controller-role-id", "some-role-id")
        self.seed("openbao-controller-secret-id", "some-secret-id")
        mock_client = MagicMock()

        cache._vault_login(mock_client)

        mock_bare_login.assert_called_once_with(mock_client, "some-role-id", "some-secret-id")


class GetSessionTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")
        self.seed("openbao-controller-role-id", "some-role-id")
        self.seed("openbao-controller-secret-id", "some-secret-id")
        patch.object(cache, "fetch_root_cert", return_value="fake-cert").start()
        self.addCleanup(patch.stopall)

    @patch("cloud_credentials.cache.hvac.Client")
    def test_logs_in_only_once_across_multiple_calls(self, mock_client_cls):
        cache._get_session()
        cache._get_session()
        cache._get_session()
        mock_client_cls.return_value.auth.approle.login.assert_called_once()

    @patch("cloud_credentials.cache.hvac.Client")
    def test_session_carries_client_and_ca_path(self, mock_client_cls):
        session = cache._get_session()
        self.assertIs(session["client"], mock_client_cls.return_value)
        self.assertTrue(Path(session["ca_path"]).exists())

    @patch("cloud_credentials.cache.hvac.Client")
    def test_client_constructed_with_a_timeout(self, mock_client_cls):
        cache._get_session()
        _, kwargs = mock_client_cls.call_args
        self.assertEqual(kwargs["timeout"], cache.TIMEOUT_SECONDS)


class VaultPathTests(unittest.TestCase):
    def test_builds_leaf_path(self):
        self.assertEqual(cache._vault_path("leaf", "backblaze-b2-write-access-key"), "cloud_credentials/leaf/backblaze-b2-write-access-key")

    def test_builds_rotation_path(self):
        self.assertEqual(cache._vault_path("rotation", "_rotation-key-cloudflare-r2-token"), "cloud_credentials/rotation/_rotation-key-cloudflare-r2-token")

    def test_rejects_unknown_category(self):
        with self.assertRaises(ValueError):
            cache._vault_path("bogus", "some-key")


class _StubbedSessionTestCase(SecretsDirTestCase):
    """Bypasses SSH/AppRole login entirely - _vault_read_at/_vault_write_at
    only need a session dict with a usable hvac.Client, however it was
    built."""

    def setUp(self):
        super().setUp()
        self.mock_client = MagicMock()
        patch.object(cache, "_get_session", return_value={"client": self.mock_client, "ca_path": "/fake/ca.pem"}).start()
        self.addCleanup(patch.stopall)


class ScopedReadWriteTests(_StubbedSessionTestCase):
    def setUp(self):
        super().setUp()
        self.cached, self.read_cache, self.write_cache, self.require_cache_file = cache.scoped("leaf")

    def test_read_cache_returns_none_on_invalid_path(self):
        self.mock_client.secrets.kv.v2.read_secret_version.side_effect = hvac.exceptions.InvalidPath
        self.assertIsNone(self.read_cache("does-not-exist"))

    def test_read_cache_returns_value_on_success(self):
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "the-value"}}}
        self.assertEqual(self.read_cache("some-key"), "the-value")

    def test_read_cache_uses_the_leaf_path_and_mount(self):
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        self.read_cache("backblaze-b2-write-access-key")
        self.mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="cloud_credentials/leaf/backblaze-b2-write-access-key",
            mount_point=openbao_client_module.VAULT_KV_MOUNT,
            raise_on_deleted_version=True,
        )

    def test_cached_false_on_invalid_path(self):
        self.mock_client.secrets.kv.v2.read_secret_version.side_effect = hvac.exceptions.InvalidPath
        self.assertFalse(self.cached("does-not-exist"))

    def test_cached_true_on_success(self):
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        self.assertTrue(self.cached("some-key"))

    def test_write_cache_writes_the_correct_payload(self):
        self.write_cache("some-key", "the-value")
        self.mock_client.secrets.kv.v2.create_or_update_secret.assert_called_once_with(
            path="cloud_credentials/leaf/some-key",
            secret={"value": "the-value"},
            mount_point=openbao_client_module.VAULT_KV_MOUNT,
        )

    def test_require_cache_file_exits_with_message_when_missing(self):
        self.mock_client.secrets.kv.v2.read_secret_version.side_effect = hvac.exceptions.InvalidPath
        with self.assertRaises(SystemExit):
            self.require_cache_file("missing-key", "run some-command to create it")

    def test_require_cache_file_returns_value_when_present(self):
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "present-value"}}}
        self.assertEqual(self.require_cache_file("present-key", "unused"), "present-value")


class VaultPathHelperTests(_StubbedSessionTestCase):
    """read_vault_path/write_vault_path - the arbitrary-path escape
    hatch outside the leaf/rotation taxonomy, e.g. hosts/* material."""

    def test_read_vault_path_uses_the_exact_given_path(self):
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        cache.read_vault_path("hosts/all/telegram/telegram-token")
        self.mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="hosts/all/telegram/telegram-token",
            mount_point=openbao_client_module.VAULT_KV_MOUNT,
            raise_on_deleted_version=True,
        )

    def test_write_vault_path_writes_to_the_exact_given_path(self):
        cache.write_vault_path("hosts/security/lldap-jwt-secret", "the-value")
        self.mock_client.secrets.kv.v2.create_or_update_secret.assert_called_once_with(
            path="hosts/security/lldap-jwt-secret",
            secret={"value": "the-value"},
            mount_point=openbao_client_module.VAULT_KV_MOUNT,
        )


class ScopedRotationCategoryTests(_StubbedSessionTestCase):
    """One test confirming scoped("rotation") writes under the other
    top-level path - the leaf-side behavior is already exercised in
    detail by ScopedReadWriteTests above, and the two categories only
    differ in which _vault_path prefix gets used."""

    def test_read_cache_uses_the_rotation_path(self):
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        _, read_cache, _, _ = cache.scoped("rotation")
        read_cache("_rotation-key-cloudflare-r2-token")
        _, kwargs = self.mock_client.secrets.kv.v2.read_secret_version.call_args
        self.assertEqual(kwargs["path"], "cloud_credentials/rotation/_rotation-key-cloudflare-r2-token")


class ScopedUnknownCategoryTests(unittest.TestCase):
    def test_raises_on_unknown_category(self):
        with self.assertRaises(ValueError):
            cache.scoped("bogus")


if __name__ == "__main__":
    unittest.main()
