"""Unit tests for openbao_client.client - the OpenBao/Vault-specific
primitives (KV v2 read/write, AppRole login, the OpenBao URL itself).

Run via `uv run pytest tools/tests/ -v`. Every Vault call is mocked;
nothing here touches a real OpenBao. The generic repo-navigation
helpers this module used to also include (main_domain, fetch_root_cert,
etc.) are tested once, directly, in tools/tests/utils/test_repo.py.
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

from openbao_client import client
from utils import repo


class SecretsDirTestCase(unittest.TestCase):
    """Base for OpenbaoBaseUrlTests - openbao_base_url() calls
    utils.repo's own main_domain() internally, which reads main-domain
    from utils.repo.SECRETS_DIR, not anything in this module."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        dir_patcher = patch.object(repo, "SECRETS_DIR", self.tmp)
        dir_patcher.start()
        self.addCleanup(dir_patcher.stop)

    def seed(self, name: str, value: str) -> None:
        (self.tmp / name).write_text(value)


class OpenbaoBaseUrlTests(SecretsDirTestCase):
    def test_builds_expected_url(self):
        self.seed("main-domain", "example.com")
        self.assertEqual(client.openbao_base_url(), "https://openbao.sec.lan.example.com:8200")


class VaultLoginTests(unittest.TestCase):
    """Bare login only - no file-reading/validation here, that's each
    caller's own job (see cache.py's/bootstrap_secrets.py's own
    VaultLoginTests for the wrapper behavior)."""

    def test_logs_in_with_the_given_role_and_secret_id(self):
        mock_client = MagicMock()

        client.vault_login(mock_client, "some-role-id", "some-secret-id")

        mock_client.auth.approle.login.assert_called_once_with(role_id="some-role-id", secret_id="some-secret-id")


class VaultReadWriteTests(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()

    def test_read_returns_none_on_invalid_path(self):
        self.mock_client.secrets.kv.v2.read_secret_version.side_effect = hvac.exceptions.InvalidPath
        self.assertIsNone(client.vault_read(self.mock_client, "some/path"))

    def test_read_returns_value_on_success(self):
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "the-value"}}}
        self.assertEqual(client.vault_read(self.mock_client, "some/path"), "the-value")

    def test_read_uses_the_default_mount_point(self):
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        client.vault_read(self.mock_client, "some/path")
        self.mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="some/path",
            mount_point=client.VAULT_KV_MOUNT,
            raise_on_deleted_version=True,
        )

    def test_read_accepts_a_mount_point_override(self):
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        client.vault_read(self.mock_client, "some/path", mount_point="other-mount")
        _, kwargs = self.mock_client.secrets.kv.v2.read_secret_version.call_args
        self.assertEqual(kwargs["mount_point"], "other-mount")

    def test_read_propagates_non_invalid_path_errors(self):
        self.mock_client.secrets.kv.v2.read_secret_version.side_effect = hvac.exceptions.Forbidden
        with self.assertRaises(hvac.exceptions.Forbidden):
            client.vault_read(self.mock_client, "some/path")

    def test_write_writes_the_correct_payload(self):
        client.vault_write(self.mock_client, "some/path", "the-value")
        self.mock_client.secrets.kv.v2.create_or_update_secret.assert_called_once_with(
            path="some/path",
            secret={"value": "the-value"},
            mount_point=client.VAULT_KV_MOUNT,
        )

    def test_write_accepts_a_mount_point_override(self):
        client.vault_write(self.mock_client, "some/path", "the-value", mount_point="other-mount")
        _, kwargs = self.mock_client.secrets.kv.v2.create_or_update_secret.call_args
        self.assertEqual(kwargs["mount_point"], "other-mount")

    def test_write_propagates_errors(self):
        self.mock_client.secrets.kv.v2.create_or_update_secret.side_effect = hvac.exceptions.Forbidden
        with self.assertRaises(hvac.exceptions.Forbidden):
            client.vault_write(self.mock_client, "some/path", "value")


if __name__ == "__main__":
    unittest.main()
