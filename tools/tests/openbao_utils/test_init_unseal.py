"""Unit tests for openbao_utils.init_unseal.

Run via `uv run pytest tools/tests/ -v`. Every SSH call is mocked;
nothing here touches a real `security` host or a real OpenBao/docker.
_DRAIN_IDLE_SECONDS is shrunk in every test that exercises _drain() -
same technique step_ca_cert's own caddy_cert_expiry molecule scenario
uses (a real threshold, made small enough to hit for real in a test),
not a mock of time itself.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from openbao_utils import init_unseal


def _mock_exec_command_result(exit_status: int = 0, stdout: bytes = b"", stderr: bytes = b""):
    """A client.exec_command() stand-in for the non-PTY (init) path -
    same 3-tuple shape as utils.repo's own _mock_ssh_client, since
    init_unseal.run_init() reads stdout/stderr directly the same way
    utils.repo.fetch_root_cert does."""
    stdin = MagicMock()
    stdout_stream = MagicMock()
    stdout_stream.read.return_value = stdout
    stdout_stream.channel.recv_exit_status.return_value = exit_status
    stderr_stream = MagicMock()
    stderr_stream.read.return_value = stderr
    return stdin, stdout_stream, stderr_stream


def _mock_pty_result(exit_status: int = 0):
    """A client.exec_command(get_pty=True) stand-in - the channel never
    reports anything ready, so _drain() idles out immediately (with
    _DRAIN_IDLE_SECONDS shrunk) and exit_status_ready() is already
    true, so run_unseal_share()'s own while-loop never spins. This
    tests the module's control flow (drain, prompt, write, drain,
    check) without simulating exact byte-level channel timing."""
    stdin = MagicMock()
    stdout_stream = MagicMock()
    channel = MagicMock()
    channel.recv_ready.return_value = False
    channel.exit_status_ready.return_value = True
    channel.recv_exit_status.return_value = exit_status
    stdout_stream.channel = channel
    return stdin, stdout_stream, MagicMock()


class ConnectTests(unittest.TestCase):
    @patch("openbao_utils.init_unseal.paramiko.SSHClient")
    @patch.object(init_unseal, "security_ssh_target", return_value=("secadmin", "security.internal.example.com", "/home/x/.ssh/key"))
    def test_connects_with_the_target_from_utils_repo(self, _mock_target, mock_ssh_client_cls):
        mock_client = MagicMock()
        mock_ssh_client_cls.return_value = mock_client
        init_unseal._connect()
        args, kwargs = mock_client.connect.call_args
        self.assertEqual(args[0], "security.internal.example.com")
        self.assertEqual(kwargs["username"], "secadmin")
        self.assertEqual(kwargs["key_filename"], "/home/x/.ssh/key")
        self.assertEqual(kwargs["timeout"], init_unseal.TIMEOUT_SECONDS)


class RunInitTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(init_unseal, "_connect")
        self.mock_connect = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_client = MagicMock()
        self.mock_connect.return_value = self.mock_client

    def test_runs_a_plain_non_interactive_docker_exec_no_it_flags(self):
        self.mock_client.exec_command.return_value = _mock_exec_command_result(exit_status=0, stdout=b"Unseal Key 1: abc")
        init_unseal.run_init()
        command = self.mock_client.exec_command.call_args.args[0]
        self.assertIn(f"docker exec {init_unseal.OPENBAO_CONTAINER} bao operator init", command)
        self.assertNotIn("-i", command.split())
        self.assertNotIn("-it", command)
        # Not requested at all for this command - see the module
        # docstring on why init needs no pty.
        self.assertNotIn("get_pty", self.mock_client.exec_command.call_args.kwargs)

    def test_prints_output_and_succeeds_on_a_clean_exit(self):
        self.mock_client.exec_command.return_value = _mock_exec_command_result(exit_status=0, stdout=b"Unseal Key 1: abc\nInitial Root Token: xyz\n")
        with patch("sys.stdout") as mock_stdout:
            result = init_unseal.run_init()
        self.assertEqual(result, 0)
        written = "".join(c.args[0] for c in mock_stdout.write.call_args_list if c.args)
        self.assertIn("Unseal Key 1: abc", written)
        self.assertIn("Initial Root Token: xyz", written)
        self.assertIn("password manager", written)

    def test_fails_loudly_on_a_nonzero_exit(self):
        self.mock_client.exec_command.return_value = _mock_exec_command_result(exit_status=2, stderr=b"Error initializing: ...")
        result = init_unseal.run_init()
        self.assertEqual(result, 1)

    def test_closes_the_client_even_on_failure(self):
        self.mock_client.exec_command.return_value = _mock_exec_command_result(exit_status=1, stderr=b"boom")
        init_unseal.run_init()
        self.mock_client.close.assert_called_once()


class RunUnsealShareTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(init_unseal, "_connect")
        self.mock_connect = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_client = MagicMock()
        self.mock_connect.return_value = self.mock_client
        drain_patcher = patch.object(init_unseal, "_DRAIN_IDLE_SECONDS", 0.01)
        drain_patcher.start()
        self.addCleanup(drain_patcher.stop)

    def test_requests_a_pty_and_keeps_the_manual_it_command(self):
        self.mock_client.exec_command.return_value = _mock_pty_result()
        with patch("getpass.getpass", return_value="fake-share"):
            init_unseal.run_unseal_share()
        args, kwargs = self.mock_client.exec_command.call_args
        self.assertIn(f"docker exec -it {init_unseal.OPENBAO_CONTAINER} bao operator unseal", args[0])
        self.assertTrue(kwargs["get_pty"])

    def test_writes_the_share_from_getpass_to_stdin_never_argv(self):
        stdin, stdout_stream, stderr_stream = _mock_pty_result()
        self.mock_client.exec_command.return_value = (stdin, stdout_stream, stderr_stream)
        with patch("getpass.getpass", return_value="fake-unseal-share") as mock_getpass:
            init_unseal.run_unseal_share()
        mock_getpass.assert_called_once()
        stdin.write.assert_called_once_with("fake-unseal-share\n")
        stdin.flush.assert_called_once()
        # The share must never appear in the command string itself.
        command = self.mock_client.exec_command.call_args.args[0]
        self.assertNotIn("fake-unseal-share", command)

    def test_fails_loudly_on_a_nonzero_remote_exit(self):
        # Confirmed live: partial progress (still sealed, threshold not
        # met) exits 0, same as a completing share - see the module
        # docstring. A nonzero exit here is a real failure to surface.
        self.mock_client.exec_command.return_value = _mock_pty_result(exit_status=1)
        with patch("getpass.getpass", return_value="fake-share"):
            result = init_unseal.run_unseal_share()
        self.assertEqual(result, 1)

    def test_succeeds_on_a_clean_exit_even_mid_threshold(self):
        # exit_status=0 covers both "fully unsealed" and "one of two
        # shares accepted, still sealed" - confirmed live, see the
        # module docstring. Either way this function reports success.
        self.mock_client.exec_command.return_value = _mock_pty_result(exit_status=0)
        with patch("getpass.getpass", return_value="fake-share"):
            result = init_unseal.run_unseal_share()
        self.assertEqual(result, 0)

    def test_closes_the_client_even_if_something_raises(self):
        self.mock_client.exec_command.side_effect = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            init_unseal.run_unseal_share()
        self.mock_client.close.assert_called_once()


class MainTests(unittest.TestCase):
    def test_dispatches_init(self):
        with patch.object(init_unseal, "run_init", return_value=0) as mock_run_init, patch.object(sys, "argv", ["prog", "init"]):
            self.assertEqual(init_unseal.main(), 0)
        mock_run_init.assert_called_once()

    def test_dispatches_unseal(self):
        with patch.object(init_unseal, "run_unseal_share", return_value=0) as mock_run_unseal, patch.object(sys, "argv", ["prog", "unseal"]):
            self.assertEqual(init_unseal.main(), 0)
        mock_run_unseal.assert_called_once()

    def test_rejects_an_unknown_action(self):
        with patch.object(sys, "argv", ["prog", "reinit"]):
            self.assertEqual(init_unseal.main(), 1)

    def test_rejects_no_action(self):
        with patch.object(sys, "argv", ["prog"]):
            self.assertEqual(init_unseal.main(), 1)


if __name__ == "__main__":
    unittest.main()
