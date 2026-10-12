"""Unit tests for openbao_utils.unseal.

Run via `uv run pytest tools/tests/ -v`. Every SSH call is mocked;
nothing here touches a real `security` host or a real OpenBao/docker.
_DRAIN_IDLE_SECONDS and _DRAIN_SETTLE_SECONDS are shrunk in every test that exercises _drain() -
same technique step_ca_cert's own caddy_cert_expiry molecule scenario
uses (a real threshold, made small enough to hit for real in a test),
not a mock of time itself.
"""

from __future__ import annotations

import time
from unittest.mock import create_autospec, patch

import pytest
from _ssh_objects import pty_result
from openbao_utils import unseal


@pytest.fixture
def connected_client(monkeypatch, ssh_client):
    monkeypatch.setattr(
        unseal,
        "security_ssh_target",
        create_autospec(unseal.security_ssh_target, return_value=("secadmin", "security.internal.example.com", "/home/x/.ssh/key")),
    )
    monkeypatch.setattr(unseal, "connect_ssh", create_autospec(unseal.connect_ssh, return_value=ssh_client))
    return ssh_client


class TestMain:
    @pytest.fixture(autouse=True)
    def _short_drain(self, monkeypatch):
        monkeypatch.setattr(unseal, "_DRAIN_IDLE_SECONDS", 0.01)
        monkeypatch.setattr(unseal, "_DRAIN_SETTLE_SECONDS", 0.01)

    def test_connects_with_the_target_from_utils_repo(self, connected_client):
        connected_client.exec_command.return_value = pty_result()
        with patch("getpass.getpass", return_value="fake-share", autospec=True):
            unseal.main()
        unseal.connect_ssh.assert_called_once_with("secadmin", "security.internal.example.com", "/home/x/.ssh/key")

    def test_requests_a_pty_and_keeps_the_manual_it_command(self, connected_client):
        connected_client.exec_command.return_value = pty_result()
        with patch("getpass.getpass", return_value="fake-share", autospec=True):
            unseal.main()
        args, kwargs = connected_client.exec_command.call_args
        assert f"docker exec -it {unseal.OPENBAO_CONTAINER} bao operator unseal" in args[0]
        assert kwargs["get_pty"]

    def test_writes_the_share_from_getpass_to_stdin_never_argv(self, connected_client):
        stdin, stdout_stream, stderr_stream = pty_result()
        connected_client.exec_command.return_value = (stdin, stdout_stream, stderr_stream)
        with patch("getpass.getpass", return_value="fake-unseal-share", autospec=True) as mock_getpass:
            unseal.main()
        mock_getpass.assert_called_once()
        stdin.write.assert_called_once_with("fake-unseal-share\n")
        stdin.flush.assert_called_once()
        # The share must never appear in the command string itself.
        command = connected_client.exec_command.call_args.args[0]
        assert "fake-unseal-share" not in command

    def test_fails_loudly_on_a_nonzero_remote_exit(self, connected_client):
        # Confirmed live: partial progress (still sealed, threshold not
        # met) exits 0, same as a completing share - see the module
        # docstring. A nonzero exit here is a real failure to surface.
        connected_client.exec_command.return_value = pty_result(exit_status=1)
        with patch("getpass.getpass", return_value="fake-share", autospec=True):
            result = unseal.main()
        assert result == 1

    def test_succeeds_on_a_clean_exit_even_mid_threshold(self, connected_client):
        # exit_status=0 covers both "fully unsealed" and "one of two
        # shares accepted, still sealed" - confirmed live, see the
        # module docstring. Either way this function reports success.
        connected_client.exec_command.return_value = pty_result(exit_status=0)
        with patch("getpass.getpass", return_value="fake-share", autospec=True):
            result = unseal.main()
        assert result == 0

    def test_reads_the_share_before_connecting(self, connected_client):
        calls: list[str] = []
        unseal.connect_ssh.side_effect = lambda *_args: calls.append("connect") or connected_client
        connected_client.exec_command.return_value = pty_result()
        with patch("getpass.getpass", side_effect=lambda _prompt="": calls.append("getpass") or "fake-share", autospec=True):
            unseal.main()
        assert calls == ["getpass", "connect"]

    def test_sends_nothing_and_fails_on_an_empty_share(self, connected_client, capsys):
        with patch("getpass.getpass", return_value="", autospec=True):
            result = unseal.main()
        assert result == 1
        unseal.connect_ssh.assert_not_called()
        assert "nothing sent" in capsys.readouterr().err

    def test_waits_for_the_remote_prompt_before_writing_the_share(self, connected_client):
        stdin, stdout_stream, stderr_stream = pty_result(chunks=(b"Unseal Key (will be hidden): ",))
        connected_client.exec_command.return_value = (stdin, stdout_stream, stderr_stream)
        recv = stdout_stream.channel.recv
        reads_when_written: list[int] = []
        stdin.write.side_effect = lambda _data: reads_when_written.append(recv.call_count)
        with patch("getpass.getpass", return_value="fake-share", autospec=True):
            unseal.main()
        assert reads_when_written == [1]

    def test_does_not_show_the_remote_prompt_after_the_share_was_read_locally(self, connected_client, capsys):
        connected_client.exec_command.return_value = pty_result(chunks=(b"Unseal Key (will be hidden): ",))
        with patch("getpass.getpass", return_value="fake-share", autospec=True):
            unseal.main()
        assert "Unseal Key" not in capsys.readouterr().out

    def test_still_shows_other_output_that_arrives_before_the_share_is_sent(self, connected_client, capsys):
        connected_client.exec_command.return_value = pty_result(chunks=(b"Error response from daemon: No such container: openbao\r\n",))
        with patch("getpass.getpass", return_value="fake-share", autospec=True):
            unseal.main()
        assert "No such container: openbao" in capsys.readouterr().out

    def test_closes_the_client_even_if_something_raises(self, connected_client):
        connected_client.exec_command.side_effect = RuntimeError("boom")
        with patch("getpass.getpass", return_value="fake-share", autospec=True), pytest.raises(RuntimeError):
            unseal.main()
        connected_client.close.assert_called_once()


class TestDrain:
    @pytest.fixture(autouse=True)
    def _long_idle_short_settle(self, monkeypatch):
        monkeypatch.setattr(unseal, "_DRAIN_IDLE_SECONDS", 30)
        monkeypatch.setattr(unseal, "_DRAIN_SETTLE_SECONDS", 0.01)

    def test_returns_once_output_goes_quiet_instead_of_waiting_out_the_idle_bound(self, capsys):
        _stdin, stdout_stream, _stderr = pty_result(chunks=(b"Unseal Key (will be hidden): ",))
        channel = stdout_stream.channel
        channel.exit_status_ready.return_value = False
        started = time.monotonic()
        unseal._drain(channel)
        assert time.monotonic() - started < 5
        assert capsys.readouterr().out == "Unseal Key (will be hidden): "

    def test_collects_the_output_without_printing_it_when_echo_is_off(self, capsys):
        _stdin, stdout_stream, _stderr = pty_result(chunks=(b"Unseal Key (will be hidden): ",))
        collected = unseal._drain(stdout_stream.channel, echo=False)
        assert collected == "Unseal Key (will be hidden): "
        assert capsys.readouterr().out == ""

    def test_returns_at_once_when_the_command_has_exited_with_nothing_to_read(self):
        _stdin, stdout_stream, _stderr = pty_result()
        started = time.monotonic()
        unseal._drain(stdout_stream.channel)
        assert time.monotonic() - started < 5
