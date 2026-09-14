"""Unit tests for cloud_credentials.cache.

Run via `uv run pytest ansible/tests/ -v`. Every SSH/Vault call is
mocked; nothing here touches a real `security` host or a real OpenBao.
Mirrors ansible/tests/test_bootstrap_secrets.py's own mocking style for
the equivalent (deliberately duplicated, not shared) plumbing.
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


def _mock_ssh_client(exit_status: int = 0, stdout: bytes = b"", stderr: bytes = b""):
    """A paramiko.SSHClient() stand-in - exec_command()'s 3-tuple, with
    stdout.channel.recv_exit_status() driving _fetch_root_cert()'s
    success/failure branch."""
    client = MagicMock()
    stdout_stream = MagicMock()
    stdout_stream.read.return_value = stdout
    stdout_stream.channel.recv_exit_status.return_value = exit_status
    stderr_stream = MagicMock()
    stderr_stream.read.return_value = stderr
    client.exec_command.return_value = (MagicMock(), stdout_stream, stderr_stream)
    return client


class SecretsDirTestCase(unittest.TestCase):
    """Base for anything touching SECRETS_DIR - main-domain and the
    controller AppRole credential are always read from here, regardless
    of which Vault path is under test. Also resets the process-lifetime
    session singleton, since it would otherwise leak a mocked
    client/ca_path across tests that don't expect one."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        dir_patcher = patch.object(cache, "SECRETS_DIR", self.tmp)
        dir_patcher.start()
        self.addCleanup(dir_patcher.stop)
        session_patcher = patch.object(cache, "_session", None)
        session_patcher.start()
        self.addCleanup(session_patcher.stop)

    def seed(self, name: str, value: str) -> None:
        (self.tmp / name).write_text(value)


class MainDomainTests(SecretsDirTestCase):
    def test_raises_system_exit_when_missing(self):
        with self.assertRaises(SystemExit):
            cache._main_domain()

    def test_returns_stripped_value(self):
        self.seed("main-domain", "  example.com  \n")
        self.assertEqual(cache._main_domain(), "example.com")


class OpenbaoBaseUrlTests(SecretsDirTestCase):
    def test_builds_expected_url(self):
        self.seed("main-domain", "example.com")
        self.assertEqual(cache._openbao_base_url(), "https://openbao.sec.lan.example.com:8200")


class FetchRootCertTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")
        patcher = patch.object(
            cache,
            "_security_ssh_target",
            return_value=("secadmin", "security.internal.example.com", "/home/x/.ssh/key"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("cloud_credentials.cache.paramiko.SSHClient")
    def test_returns_stdout_on_success(self, mock_ssh_client_cls):
        mock_ssh_client_cls.return_value = _mock_ssh_client(exit_status=0, stdout=b"-----BEGIN CERTIFICATE-----\n...")
        cert = cache._fetch_root_cert()
        self.assertIn("BEGIN CERTIFICATE", cert)

    @patch("cloud_credentials.cache.paramiko.SSHClient")
    def test_raises_system_exit_on_nonzero_exit_status(self, mock_ssh_client_cls):
        mock_ssh_client_cls.return_value = _mock_ssh_client(exit_status=1, stderr=b"Permission denied")
        with self.assertRaises(SystemExit):
            cache._fetch_root_cert()

    @patch("cloud_credentials.cache.paramiko.SSHClient")
    def test_connects_to_the_correct_host_and_execs_the_correct_command(self, mock_ssh_client_cls):
        mock_client = _mock_ssh_client(exit_status=0, stdout=b"cert")
        mock_ssh_client_cls.return_value = mock_client
        cache._fetch_root_cert()
        args, kwargs = mock_client.connect.call_args
        self.assertEqual(args[0], "security.internal.example.com")
        self.assertEqual(kwargs["username"], "secadmin")
        self.assertEqual(kwargs["key_filename"], "/home/x/.ssh/key")
        command = mock_client.exec_command.call_args.args[0]
        self.assertIn(cache.VAULT_STEP_CA_CONTAINER, command)
        self.assertIn("/home/step/certs/root_ca.crt", command)

    @patch("cloud_credentials.cache.paramiko.SSHClient")
    def test_connects_with_a_timeout(self, mock_ssh_client_cls):
        mock_client = _mock_ssh_client(exit_status=0)
        mock_ssh_client_cls.return_value = mock_client
        cache._fetch_root_cert()
        _, kwargs = mock_client.connect.call_args
        self.assertEqual(kwargs["timeout"], cache._TIMEOUT_SECONDS)

    @patch("cloud_credentials.cache.paramiko.SSHClient")
    def test_closes_the_client_even_on_failure(self, mock_ssh_client_cls):
        mock_client = _mock_ssh_client(exit_status=1, stderr=b"boom")
        mock_ssh_client_cls.return_value = mock_client
        with self.assertRaises(SystemExit):
            cache._fetch_root_cert()
        mock_client.close.assert_called_once()


class VaultLoginTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")

    def test_raises_system_exit_when_role_id_missing(self):
        self.seed("openbao-controller-secret-id", "some-secret-id")
        with self.assertRaises(SystemExit):
            cache._vault_login(MagicMock())

    def test_logs_in_with_role_id_and_secret_id(self):
        self.seed("openbao-controller-role-id", "some-role-id")
        self.seed("openbao-controller-secret-id", "some-secret-id")
        mock_client = MagicMock()

        cache._vault_login(mock_client)

        mock_client.auth.approle.login.assert_called_once_with(role_id="some-role-id", secret_id="some-secret-id")


class GetSessionTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")
        self.seed("openbao-controller-role-id", "some-role-id")
        self.seed("openbao-controller-secret-id", "some-secret-id")
        patch.object(cache, "_fetch_root_cert", return_value="fake-cert").start()
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
        self.assertEqual(kwargs["timeout"], cache._TIMEOUT_SECONDS)


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
            mount_point=cache.VAULT_KV_MOUNT,
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
            mount_point=cache.VAULT_KV_MOUNT,
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
            mount_point=cache.VAULT_KV_MOUNT,
        )

    def test_write_vault_path_writes_to_the_exact_given_path(self):
        cache.write_vault_path("hosts/security/lldap-jwt-secret", "the-value")
        self.mock_client.secrets.kv.v2.create_or_update_secret.assert_called_once_with(
            path="hosts/security/lldap-jwt-secret",
            secret={"value": "the-value"},
            mount_point=cache.VAULT_KV_MOUNT,
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
