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
from unittest.mock import create_autospec, patch

import paramiko
import pytest
from _ssh_objects import exec_result
from utils import repo


@pytest.fixture
def inventory_path(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path_factory.mktemp("inventory") / "inventory.yaml"
    monkeypatch.setattr(repo, "INVENTORY_PATH", path)
    monkeypatch.setattr(repo, "GENERATED_INVENTORY_PATH", path.with_name("tofu-hosts.yaml"))
    return path


class TestSecretsDirFrom:
    def test_defaults_to_the_checkouts_file_cache(self):
        assert repo.secrets_dir_from({}) == repo.PROJECT_ROOT / "ansible/files/secrets"

    def test_an_empty_value_is_unset(self):
        assert repo.secrets_dir_from({repo.SECRETS_DIR_ENV: ""}) == repo.PROJECT_ROOT / "ansible/files/secrets"

    def test_an_absolute_value_replaces_the_default(self):
        assert repo.secrets_dir_from({repo.SECRETS_DIR_ENV: "/etc/cd-agent/credentials/deploy"}) == Path("/etc/cd-agent/credentials/deploy")

    @pytest.mark.parametrize("value", ["credentials", "./credentials", "~/credentials"], ids=["bare", "dot", "tilde"])
    def test_a_relative_value_is_refused(self, value, capsys):
        with pytest.raises(SystemExit):
            repo.secrets_dir_from({repo.SECRETS_DIR_ENV: value})
        assert f"{repo.SECRETS_DIR_ENV} must be an absolute path, got {value!r}" in capsys.readouterr().err


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

    def test_takes_the_user_from_the_generated_inventory_when_the_hand_written_entry_has_none(self, inventory_path):
        inventory_path.write_text(
            "all:\n  vars:\n    ansible_ssh_private_key_file: ~/.ssh/some_key\n  children:\n    managed_hosts:\n      hosts:\n        security:\n"
        )
        repo.GENERATED_INVENTORY_PATH.write_text("all:\n  hosts:\n    security:\n      ansible_host: 192.168.20.5\n      ansible_user: generatedadmin\n")
        assert repo.security_ssh_target()[0] == "generatedadmin"

    def test_the_generated_user_wins_over_the_hand_written_one(self, inventory_path):
        inventory_path.write_text(
            "all:\n  vars:\n    ansible_ssh_private_key_file: ~/.ssh/some_key\n  children:\n    managed_hosts:\n      hosts:\n"
            "        security:\n          ansible_user: oldadmin\n"
        )
        repo.GENERATED_INVENTORY_PATH.write_text("all:\n  hosts:\n    security:\n      ansible_user: generatedadmin\n")
        assert repo.security_ssh_target()[0] == "generatedadmin"

    def test_stops_with_a_message_when_neither_file_names_a_user(self, inventory_path, capsys):
        inventory_path.write_text(
            "all:\n  vars:\n    ansible_ssh_private_key_file: ~/.ssh/some_key\n  children:\n    managed_hosts:\n      hosts:\n        security:\n"
        )
        with pytest.raises(SystemExit):
            repo.security_ssh_target()
        assert "tofu_inventory" in capsys.readouterr().err


class TestSshTarget:
    @pytest.fixture(autouse=True)
    def _main_domain_and_inventory(self, secrets_dir, inventory_path):
        secrets_dir.seed("main-domain", "example.com")
        inventory_path.write_text(
            "all:\n  vars:\n    ansible_ssh_private_key_file: ~/.ssh/some_key\n  children:\n"
            "    managed_hosts:\n      hosts:\n        services:\n          ansible_user: svcadmin\n        play:\n"
            "    network_infra:\n      hosts:\n        tailscale:\n          ansible_user: tsadmin\n"
        )

    def test_a_host_of_managed_hosts_has_its_own_user_and_name(self):
        assert repo.ssh_target("services")[:2] == ("svcadmin", "services.internal.example.com")

    def test_a_host_of_network_infra_is_found_too(self):
        assert repo.ssh_target("tailscale")[:2] == ("tsadmin", "tailscale.internal.example.com")

    def test_a_host_with_an_empty_entry_takes_its_user_from_the_generated_inventory(self):
        repo.GENERATED_INVENTORY_PATH.write_text("all:\n  hosts:\n    play:\n      ansible_user: playadmin\n")
        assert repo.ssh_target("play")[0] == "playadmin"

    def test_a_host_in_no_group_stops_with_a_message_naming_it(self, capsys):
        with pytest.raises(SystemExit):
            repo.ssh_target("nowhere")
        assert "No ansible_user for nowhere" in capsys.readouterr().err


class TestConnectSsh:
    @patch("utils.repo.paramiko.SSHClient", autospec=True)
    def test_connects_with_the_given_target_and_a_timeout(self, mock_ssh_client_cls, ssh_client):
        mock_ssh_client_cls.return_value = ssh_client
        client = repo.connect_ssh("secadmin", "security.internal.example.com", "/home/x/.ssh/key")
        assert client is ssh_client
        args, kwargs = ssh_client.connect.call_args
        assert args[0] == "security.internal.example.com"
        assert kwargs["username"] == "secadmin"
        assert kwargs["key_filename"] == "/home/x/.ssh/key"
        assert kwargs["timeout"] == repo.TIMEOUT_SECONDS

    @patch("utils.repo.paramiko.SSHClient", autospec=True)
    def test_loads_the_system_keys_and_remembers_a_new_host_in_the_users_known_hosts(self, mock_ssh_client_cls, ssh_client):
        mock_ssh_client_cls.return_value = ssh_client
        repo.connect_ssh("secadmin", "security.internal.example.com", "/home/x/.ssh/key")
        ssh_client.load_system_host_keys.assert_called_once_with()
        policy = ssh_client._policy  # paramiko offers no getter for the policy it was given
        assert isinstance(policy, repo.RememberFirstKey)
        assert policy.known_hosts == repo.KNOWN_HOSTS

    @patch("utils.repo.paramiko.SSHClient", autospec=True)
    def test_closes_the_client_and_reraises_when_the_connection_fails(self, mock_ssh_client_cls, ssh_client):
        mock_ssh_client_cls.return_value = ssh_client
        ssh_client.connect.side_effect = OSError("unreachable")
        with pytest.raises(OSError, match="unreachable"):
            repo.connect_ssh("secadmin", "security.internal.example.com", "/home/x/.ssh/key")
        ssh_client.close.assert_called_once()


class TestRememberFirstKey:
    @pytest.fixture
    def known_hosts(self, tmp_path: Path) -> Path:
        return tmp_path / "home" / ".ssh" / "known_hosts"

    @pytest.fixture
    def key(self) -> paramiko.PKey:
        return paramiko.ECDSAKey.generate()

    def test_writes_the_first_key_to_the_file_and_a_later_client_finds_it(self, known_hosts, key):
        repo.RememberFirstKey(known_hosts).missing_host_key(paramiko.SSHClient(), "security.internal.example.com", key)

        later = paramiko.SSHClient()
        later.load_host_keys(str(known_hosts))
        remembered = later.get_host_keys().lookup("security.internal.example.com")
        assert remembered is not None
        assert remembered[key.get_name()] == key

    def test_creates_the_ssh_directory_private(self, known_hosts, key):
        repo.RememberFirstKey(known_hosts).missing_host_key(paramiko.SSHClient(), "security.internal.example.com", key)

        assert known_hosts.parent.stat().st_mode & 0o777 == 0o700

    def test_appends_without_touching_the_lines_already_there(self, known_hosts, key):
        known_hosts.parent.mkdir(parents=True)
        known_hosts.write_text("# kept\n@cert-authority *.example.com ssh-ed25519 AAAA\n")

        repo.RememberFirstKey(known_hosts).missing_host_key(paramiko.SSHClient(), "a.example.com", key)

        lines = known_hosts.read_text().splitlines()
        assert lines[:2] == ["# kept", "@cert-authority *.example.com ssh-ed25519 AAAA"]
        assert lines[2].startswith("a.example.com ")

    def test_the_same_client_accepts_the_host_again_without_a_second_line(self, known_hosts, key):
        client = paramiko.SSHClient()
        policy = repo.RememberFirstKey(known_hosts)
        policy.missing_host_key(client, "a.example.com", key)

        assert client.get_host_keys().check("a.example.com", key)
        assert len(known_hosts.read_text().splitlines()) == 1

    def test_says_which_host_and_key_it_remembered(self, known_hosts, key, capsys):
        repo.RememberFirstKey(known_hosts).missing_host_key(paramiko.SSHClient(), "a.example.com", key)

        err = capsys.readouterr().err
        assert "a.example.com" in err
        assert key.fingerprint in err


class TestFetchRootCert:
    @pytest.fixture(autouse=True)
    def _main_domain_and_ssh_target(self, secrets_dir, monkeypatch):
        secrets_dir.seed("main-domain", "example.com")
        monkeypatch.setattr(
            repo,
            "security_ssh_target",
            create_autospec(repo.security_ssh_target, return_value=("secadmin", "security.internal.example.com", "/home/x/.ssh/key")),
        )

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


class TestRootCert:
    @pytest.fixture
    def fetch(self, monkeypatch):
        mock = create_autospec(repo.fetch_root_cert, return_value="fetched-cert")
        monkeypatch.setattr(repo, "fetch_root_cert", mock)
        return mock

    def test_fetches_from_security_when_nothing_was_delivered(self, secrets_dir, fetch):
        assert repo.root_cert() == "fetched-cert"
        fetch.assert_called_once_with()

    def test_returns_the_delivered_copy_without_fetching(self, secrets_dir, fetch):
        secrets_dir.seed(repo.ROOT_CERT_FILE, "-----BEGIN CERTIFICATE-----\ndelivered\n-----END CERTIFICATE-----\n")
        assert repo.root_cert() == "-----BEGIN CERTIFICATE-----\ndelivered\n-----END CERTIFICATE-----"
        fetch.assert_not_called()

    @pytest.mark.parametrize("content", ["", "not a certificate"], ids=["blank", "text"])
    def test_refuses_a_delivered_file_that_is_not_a_certificate(self, secrets_dir, fetch, capsys, content):
        secrets_dir.seed(repo.ROOT_CERT_FILE, content)
        with pytest.raises(SystemExit):
            repo.root_cert()
        assert str(secrets_dir.path / repo.ROOT_CERT_FILE) in capsys.readouterr().err
        fetch.assert_not_called()
