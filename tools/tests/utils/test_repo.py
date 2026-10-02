"""Unit tests for utils.repo - the generic repo-navigation and
homelab-wide bootstrap helpers extracted from openbao_utils.client
(they were never actually OpenBao-specific, just its first consumer).

Run via `uv run pytest tools/tests/ -v`. Every SSH call is mocked;
nothing here touches a real `security` host. openbao_utils.client's
own tests mock these functions rather than re-testing their behavior
here - see that module's own comment on why.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from _ssh_objects import exec_result
from utils import repo


@pytest.fixture
def inventory_path(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path_factory.mktemp("inventory") / "inventory.yaml"
    monkeypatch.setattr(repo, "INVENTORY_PATH", path)
    return path


@pytest.mark.usefixtures("secrets_dir")
class TestReadBootstrapFile:
    def test_returns_none_when_missing(self):
        assert repo.read_bootstrap_file("does-not-exist") is None

    def test_returns_stripped_content_when_present(self, secrets_dir):
        secrets_dir.seed("some-file", "  value  \n")
        assert repo.read_bootstrap_file("some-file") == "value"


@pytest.mark.usefixtures("secrets_dir")
class TestMainDomain:
    def test_raises_system_exit_when_missing(self):
        with pytest.raises(SystemExit):
            repo.main_domain()

    def test_returns_stripped_value(self, secrets_dir):
        secrets_dir.seed("main-domain", "  example.com  \n")
        assert repo.main_domain() == "example.com"


class TestSecurityCredentialsSshTarget:
    @pytest.fixture(autouse=True)
    def _main_domain_and_inventory(self, secrets_dir, inventory_path):
        secrets_dir.seed("main-domain", "example.com")

    def test_reads_user_and_key_path_from_inventory_not_hardcoded(self, inventory_path):
        inventory_path.write_text(
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
        assert user == "someadmin"
        assert host == "security.internal.example.com"
        assert key_path == str(Path("~/.ssh/some_key").expanduser())


class TestFetchRootCert:
    @pytest.fixture(autouse=True)
    def _main_domain_and_ssh_target(self, secrets_dir, monkeypatch):
        secrets_dir.seed("main-domain", "example.com")
        monkeypatch.setattr(repo, "security_ssh_target", lambda: ("secadmin", "security.internal.example.com", "/home/x/.ssh/key"))

    @patch("utils.repo.paramiko.SSHClient", autospec=True)
    def test_returns_stdout_on_success(self, mock_ssh_client_cls, ssh_client):
        mock_ssh_client_cls.return_value = ssh_client
        ssh_client.exec_command.return_value = exec_result(exit_status=0, stdout=b"-----BEGIN CERTIFICATE-----\n...")
        cert = repo.fetch_root_cert()
        assert "BEGIN CERTIFICATE" in cert

    @patch("utils.repo.paramiko.SSHClient", autospec=True)
    def test_connects_to_the_correct_host_and_execs_the_correct_command(self, mock_ssh_client_cls, ssh_client):
        mock_ssh_client_cls.return_value = ssh_client
        ssh_client.exec_command.return_value = exec_result(exit_status=0, stdout=b"cert")
        repo.fetch_root_cert()
        args, kwargs = ssh_client.connect.call_args
        assert args[0] == "security.internal.example.com"
        assert kwargs["username"] == "secadmin"
        assert kwargs["key_filename"] == "/home/x/.ssh/key"
        command = ssh_client.exec_command.call_args.args[0]
        assert repo.STEP_CA_CONTAINER in command
        assert "/home/step/certs/root_ca.crt" in command

    @patch("utils.repo.paramiko.SSHClient", autospec=True)
    def test_connects_with_a_timeout(self, mock_ssh_client_cls, ssh_client):
        mock_ssh_client_cls.return_value = ssh_client
        ssh_client.exec_command.return_value = exec_result(exit_status=0)
        repo.fetch_root_cert()
        _, kwargs = ssh_client.connect.call_args
        assert kwargs["timeout"] == repo.TIMEOUT_SECONDS

    @patch("utils.repo.paramiko.SSHClient", autospec=True)
    def test_raises_system_exit_on_nonzero_exit_status(self, mock_ssh_client_cls, ssh_client):
        mock_ssh_client_cls.return_value = ssh_client
        ssh_client.exec_command.return_value = exec_result(exit_status=1, stderr=b"Permission denied")
        with pytest.raises(SystemExit):
            repo.fetch_root_cert()

    @patch("utils.repo.paramiko.SSHClient", autospec=True)
    def test_closes_the_client_even_on_failure(self, mock_ssh_client_cls, ssh_client):
        mock_ssh_client_cls.return_value = ssh_client
        ssh_client.exec_command.return_value = exec_result(exit_status=1, stderr=b"boom")
        with pytest.raises(SystemExit):
            repo.fetch_root_cert()
        ssh_client.close.assert_called_once()
