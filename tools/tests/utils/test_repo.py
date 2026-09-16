"""Unit tests for utils.repo - the generic repo-navigation and
homelab-wide bootstrap helpers extracted from openbao_utils.client
(they were never actually OpenBao-specific, just its first consumer).

Run via `uv run pytest tools/tests/ -v`. Every SSH call is mocked;
nothing here touches a real `security` host. openbao_utils.client's
own tests mock these functions rather than re-testing their behavior
here - see that module's own comment on why.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from utils import repo


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
        dir_patcher = patch.object(repo, "SECRETS_DIR", self.tmp)
        dir_patcher.start()
        self.addCleanup(dir_patcher.stop)

    def seed(self, name: str, value: str) -> None:
        (self.tmp / name).write_text(value)


class ReadBootstrapFileTests(SecretsDirTestCase):
    def test_returns_none_when_missing(self):
        self.assertIsNone(repo.read_bootstrap_file("does-not-exist"))

    def test_returns_stripped_content_when_present(self):
        self.seed("some-file", "  value  \n")
        self.assertEqual(repo.read_bootstrap_file("some-file"), "value")


class MainDomainTests(SecretsDirTestCase):
    def test_raises_system_exit_when_missing(self):
        with self.assertRaises(SystemExit):
            repo.main_domain()

    def test_returns_stripped_value(self):
        self.seed("main-domain", "  example.com  \n")
        self.assertEqual(repo.main_domain(), "example.com")


class SecurityCredentialsSshTargetTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")
        self.inventory_tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.inventory_tmp, ignore_errors=True))
        self.inventory_path = self.inventory_tmp / "inventory.yaml"
        patcher = patch.object(repo, "INVENTORY_PATH", self.inventory_path)
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
        user, host, key_path = repo.security_ssh_target()
        self.assertEqual(user, "someadmin")
        self.assertEqual(host, "security.internal.example.com")
        self.assertEqual(key_path, str(Path("~/.ssh/some_key").expanduser()))


class FetchRootCertTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")
        patcher = patch.object(
            repo,
            "security_ssh_target",
            return_value=("secadmin", "security.internal.example.com", "/home/x/.ssh/key"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("utils.repo.paramiko.SSHClient")
    def test_returns_stdout_on_success(self, mock_ssh_client_cls):
        mock_ssh_client_cls.return_value = _mock_ssh_client(exit_status=0, stdout=b"-----BEGIN CERTIFICATE-----\n...")
        cert = repo.fetch_root_cert()
        self.assertIn("BEGIN CERTIFICATE", cert)

    @patch("utils.repo.paramiko.SSHClient")
    def test_connects_to_the_correct_host_and_execs_the_correct_command(self, mock_ssh_client_cls):
        mock_ssh_client = _mock_ssh_client(exit_status=0, stdout=b"cert")
        mock_ssh_client_cls.return_value = mock_ssh_client
        repo.fetch_root_cert()
        args, kwargs = mock_ssh_client.connect.call_args
        self.assertEqual(args[0], "security.internal.example.com")
        self.assertEqual(kwargs["username"], "secadmin")
        self.assertEqual(kwargs["key_filename"], "/home/x/.ssh/key")
        command = mock_ssh_client.exec_command.call_args.args[0]
        self.assertIn(repo.STEP_CA_CONTAINER, command)
        self.assertIn("/home/step/certs/root_ca.crt", command)

    @patch("utils.repo.paramiko.SSHClient")
    def test_connects_with_a_timeout(self, mock_ssh_client_cls):
        mock_ssh_client = _mock_ssh_client(exit_status=0)
        mock_ssh_client_cls.return_value = mock_ssh_client
        repo.fetch_root_cert()
        _, kwargs = mock_ssh_client.connect.call_args
        self.assertEqual(kwargs["timeout"], repo.TIMEOUT_SECONDS)

    @patch("utils.repo.paramiko.SSHClient")
    def test_raises_system_exit_on_nonzero_exit_status(self, mock_ssh_client_cls):
        mock_ssh_client_cls.return_value = _mock_ssh_client(exit_status=1, stderr=b"Permission denied")
        with self.assertRaises(SystemExit):
            repo.fetch_root_cert()

    @patch("utils.repo.paramiko.SSHClient")
    def test_closes_the_client_even_on_failure(self, mock_ssh_client_cls):
        mock_ssh_client = _mock_ssh_client(exit_status=1, stderr=b"boom")
        mock_ssh_client_cls.return_value = mock_ssh_client
        with self.assertRaises(SystemExit):
            repo.fetch_root_cert()
        mock_ssh_client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
