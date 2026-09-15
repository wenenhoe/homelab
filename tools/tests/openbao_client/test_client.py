"""Unit tests for openbao_client.client - the generic OpenBao/Vault
primitives shared by cloud_credentials/cache.py and bootstrap_secrets.py.

Run via `uv run pytest tools/tests/ -v`. Every SSH/Vault call is
mocked; nothing here touches a real `security` host or a real OpenBao.
cache.py's and bootstrap_secrets.py's own tests mock this module's
functions rather than re-testing their behavior here - see each
file's own comment on why.
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


def _mock_ssh_client(exit_status: int = 0, stdout: bytes = b"", stderr: bytes = b""):
    """A paramiko.SSHClient() stand-in - exec_command()'s 3-tuple, with
    stdout.channel.recv_exit_status() driving fetch_root_cert()'s
    success/failure branch."""
    ssh_client = MagicMock()
    stdout_stream = MagicMock()
    stdout_stream.read.return_value = stdout
    stdout_stream.channel.recv_exit_status.return_value = exit_status
    stderr_stream = MagicMock()
    stderr_stream.read.return_value = stderr
    ssh_client.exec_command.return_value = (MagicMock(), stdout_stream, stderr_stream)
    return ssh_client


class SecretsDirTestCase(unittest.TestCase):
    """Base for anything touching SECRETS_DIR - main-domain and the
    controller AppRole credential are always read from here, regardless
    of which function is under test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        dir_patcher = patch.object(client, "SECRETS_DIR", self.tmp)
        dir_patcher.start()
        self.addCleanup(dir_patcher.stop)

    def seed(self, name: str, value: str) -> None:
        (self.tmp / name).write_text(value)


class ReadBootstrapFileTests(SecretsDirTestCase):
    def test_returns_none_when_missing(self):
        self.assertIsNone(client.read_bootstrap_file("does-not-exist"))

    def test_returns_stripped_content_when_present(self):
        self.seed("some-file", "  value  \n")
        self.assertEqual(client.read_bootstrap_file("some-file"), "value")


class MainDomainTests(SecretsDirTestCase):
    def test_raises_system_exit_when_missing(self):
        with self.assertRaises(SystemExit):
            client.main_domain()

    def test_returns_stripped_value(self):
        self.seed("main-domain", "  example.com  \n")
        self.assertEqual(client.main_domain(), "example.com")


class OpenbaoBaseUrlTests(SecretsDirTestCase):
    def test_builds_expected_url(self):
        self.seed("main-domain", "example.com")
        self.assertEqual(client.openbao_base_url(), "https://openbao.sec.lan.example.com:8200")


class SecurityCredentialsSshTargetTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")
        self.inventory_tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.inventory_tmp, ignore_errors=True))
        self.inventory_path = self.inventory_tmp / "inventory.yaml"
        patcher = patch.object(client, "INVENTORY_PATH", self.inventory_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reads_user_and_key_path_from_inventory_not_hardcoded(self):
        self.inventory_path.write_text(
            "all:\n"
            "  vars:\n"
            "    ansible_ssh_private_key_file: ~/.ssh/some_key\n"
            "  children:\n"
            "    managed_hosts:\n"
            "      hosts:\n"
            "        security:\n"
            "          ansible_user: someadmin\n"
        )
        user, host, key_path = client.security_ssh_target()
        self.assertEqual(user, "someadmin")
        self.assertEqual(host, "security.internal.example.com")
        self.assertEqual(key_path, str(Path("~/.ssh/some_key").expanduser()))


class FetchRootCertTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")
        patcher = patch.object(
            client,
            "security_ssh_target",
            return_value=("secadmin", "security.internal.example.com", "/home/x/.ssh/key"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("openbao_client.client.paramiko.SSHClient")
    def test_returns_stdout_on_success(self, mock_ssh_client_cls):
        mock_ssh_client_cls.return_value = _mock_ssh_client(exit_status=0, stdout=b"-----BEGIN CERTIFICATE-----\n...")
        cert = client.fetch_root_cert()
        self.assertIn("BEGIN CERTIFICATE", cert)

    @patch("openbao_client.client.paramiko.SSHClient")
    def test_connects_to_the_correct_host_and_execs_the_correct_command(self, mock_ssh_client_cls):
        mock_ssh_client = _mock_ssh_client(exit_status=0, stdout=b"cert")
        mock_ssh_client_cls.return_value = mock_ssh_client
        client.fetch_root_cert()
        args, kwargs = mock_ssh_client.connect.call_args
        self.assertEqual(args[0], "security.internal.example.com")
        self.assertEqual(kwargs["username"], "secadmin")
        self.assertEqual(kwargs["key_filename"], "/home/x/.ssh/key")
        command = mock_ssh_client.exec_command.call_args.args[0]
        self.assertIn(client.VAULT_STEP_CA_CONTAINER, command)
        self.assertIn("/home/step/certs/root_ca.crt", command)

    @patch("openbao_client.client.paramiko.SSHClient")
    def test_connects_with_a_timeout(self, mock_ssh_client_cls):
        mock_ssh_client = _mock_ssh_client(exit_status=0)
        mock_ssh_client_cls.return_value = mock_ssh_client
        client.fetch_root_cert()
        _, kwargs = mock_ssh_client.connect.call_args
        self.assertEqual(kwargs["timeout"], client.TIMEOUT_SECONDS)

    @patch("openbao_client.client.paramiko.SSHClient")
    def test_raises_system_exit_on_nonzero_exit_status(self, mock_ssh_client_cls):
        mock_ssh_client_cls.return_value = _mock_ssh_client(exit_status=1, stderr=b"Permission denied")
        with self.assertRaises(SystemExit):
            client.fetch_root_cert()

    @patch("openbao_client.client.paramiko.SSHClient")
    def test_closes_the_client_even_on_failure(self, mock_ssh_client_cls):
        mock_ssh_client = _mock_ssh_client(exit_status=1, stderr=b"boom")
        mock_ssh_client_cls.return_value = mock_ssh_client
        with self.assertRaises(SystemExit):
            client.fetch_root_cert()
        mock_ssh_client.close.assert_called_once()


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
