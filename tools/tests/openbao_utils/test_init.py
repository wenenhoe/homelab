"""Unit tests for openbao_utils.init.

Run via `uv run pytest tools/tests/ -v`. Every SSH call is mocked;
nothing here touches a real `security` host or a real OpenBao/docker.
"""

from __future__ import annotations

from unittest.mock import create_autospec, patch

import pytest
from _ssh_objects import chunked_result
from openbao_utils import init
from utils.repo import TIMEOUT_SECONDS


@pytest.fixture
def connected_client(monkeypatch, ssh_client):
    monkeypatch.setattr(
        init, "security_ssh_target", create_autospec(init.security_ssh_target, return_value=("secadmin", "security.internal.example.com", "/home/x/.ssh/key"))
    )
    monkeypatch.setattr(init, "connect_ssh", create_autospec(init.connect_ssh, return_value=ssh_client))
    return ssh_client


class TestMain:
    def test_runs_a_plain_non_interactive_docker_exec_no_it_flags(self, connected_client):
        connected_client.exec_command.return_value = chunked_result((b"Unseal Key 1: abc",))
        init.main()
        command = connected_client.exec_command.call_args.args[0]
        assert f"docker exec {init.OPENBAO_CONTAINER} bao operator init" in command
        assert "-i" not in command.split()
        assert "-it" not in command
        # Not requested at all for this command - see the module
        # docstring on why init needs no pty.
        assert "get_pty" not in connected_client.exec_command.call_args.kwargs

    def test_prints_output_and_succeeds_on_a_clean_exit(self, connected_client):
        connected_client.exec_command.return_value = chunked_result((b"Unseal Key 1: abc\n", b"Initial Root Token: xyz\n"))
        with patch("sys.stdout", autospec=True) as mock_stdout:
            result = init.main()
        assert result == 0
        written = "".join(c.args[0] for c in mock_stdout.write.call_args_list if c.args)
        assert "Unseal Key 1: abc" in written
        assert "Initial Root Token: xyz" in written
        assert "password manager" in written

    def test_fails_loudly_on_a_nonzero_exit(self, connected_client):
        connected_client.exec_command.return_value = chunked_result(stderr=b"Error initializing: ...", exit_status=2)
        result = init.main()
        assert result == 1

    def test_connects_with_the_target_from_utils_repo(self, connected_client):
        connected_client.exec_command.return_value = chunked_result()
        init.main()
        init.connect_ssh.assert_called_once_with("secadmin", "security.internal.example.com", "/home/x/.ssh/key")

    def test_closes_the_client_even_on_failure(self, connected_client):
        connected_client.exec_command.return_value = chunked_result(stderr=b"boom", exit_status=1)
        assert init.main() == 1
        connected_client.close.assert_called_once()

    def test_waits_longer_per_read_than_the_connection_timeout(self, connected_client):
        connected_client.exec_command.return_value = chunked_result()
        init.main()
        assert connected_client.exec_command.call_args.kwargs["timeout"] == init.INIT_TIMEOUT_SECONDS
        assert init.INIT_TIMEOUT_SECONDS > TIMEOUT_SECONDS

    def test_shows_the_shares_that_arrived_before_a_silence_and_says_what_it_may_mean(self, connected_client, capsys):
        connected_client.exec_command.return_value = chunked_result((b"Unseal Key 1: abc\n",), then_timeout=True)
        result = init.main()
        captured = capsys.readouterr()
        assert result == 1
        assert "Unseal Key 1: abc" in captured.out
        assert "may still be running" in captured.err
        assert "Do not run it again yet" in captured.err
        assert "If init's output was lost" in captured.err
        connected_client.close.assert_called_once()

    def test_a_silence_with_no_output_at_all_is_reported_the_same_way(self, connected_client, capsys):
        connected_client.exec_command.return_value = chunked_result(then_timeout=True)
        assert init.main() == 1
        assert "finished with its output lost" in capsys.readouterr().err

    def test_an_init_that_already_happened_says_the_shares_are_lost_if_unseen(self, connected_client, capsys):
        connected_client.exec_command.return_value = chunked_result(stderr=b"* Vault is already initialized\n", exit_status=2)
        assert init.main() == 1
        assert "they are lost" in capsys.readouterr().err

    def test_other_failures_do_not_claim_the_shares_are_lost(self, connected_client, capsys):
        connected_client.exec_command.return_value = chunked_result(stderr=b"connection refused\n", exit_status=2)
        assert init.main() == 1
        assert "lost" not in capsys.readouterr().err
