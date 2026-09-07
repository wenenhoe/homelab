"""Unit tests for bootstrap_secrets.py.

Run via `uv run pytest ansible/tests/ -v`. Every SSH/Vault call is
mocked; nothing here touches a real `security` host or a real OpenBao.
bootstrap_secrets.py has its own independent SECRETS_DIR/REGISTRY_PATH/
INVENTORY_PATH (it's a standalone top-level script, not part of the
cloud_credentials package), so this patches those directly rather than
cloud_credentials.cache.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bootstrap_secrets


def _mock_response(status_code: int, json_body: dict | None = None):
    resp = MagicMock(status_code=status_code)
    resp.json.return_value = json_body or {}
    resp.raise_for_status = MagicMock() if status_code < 400 else MagicMock(side_effect=requests.exceptions.HTTPError(str(status_code)))
    return resp


class SecretsDirTestCase(unittest.TestCase):
    """Base for anything touching SECRETS_DIR — every Vault/inventory test
    also needs this, since main_domain/role_id/secret_id are always read
    from here regardless of which path is under test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(bootstrap_secrets, "SECRETS_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def seed(self, name: str, value: str) -> None:
        (self.tmp / name).write_text(value)


class RegistryLoadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.registry_path = self.tmp / "secrets_registry.yaml"
        patcher = patch.object(bootstrap_secrets, "REGISTRY_PATH", self.registry_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_registry(self, content: str) -> None:
        self.registry_path.write_text(content)

    def test_load_registry_returns_the_secrets_registry_key(self):
        self.write_registry("secrets_registry:\n  main-domain: { format: manual }\n")
        self.assertEqual(bootstrap_secrets.load_registry(), {"main-domain": {"format": "manual"}})

    def test_load_manual_entries_excludes_hex_and_uuid4(self):
        self.write_registry("secrets_registry:\n  main-domain: { format: manual }\n  some-hex: { format: hex, length: 32 }\n  some-uuid: { format: uuid4 }\n")
        registry = bootstrap_secrets.load_registry()
        manual = bootstrap_secrets.load_manual_entries(registry)
        self.assertEqual(list(manual.keys()), ["main-domain"])


class ReadCacheFileTests(SecretsDirTestCase):
    def test_returns_none_when_missing(self):
        self.assertIsNone(bootstrap_secrets.read_cache_file("does-not-exist"))

    def test_returns_content_when_present(self):
        self.seed("main-domain", "example.com")
        self.assertEqual(bootstrap_secrets.read_cache_file("main-domain"), "example.com")


class PromptForValueTests(unittest.TestCase):
    @patch("builtins.input", return_value="typed-value")
    def test_non_sensitive_uses_input(self, mock_input):
        value = bootstrap_secrets.prompt_for_value("some-key", {"description": "d", "sensitive": False})
        self.assertEqual(value, "typed-value")
        mock_input.assert_called_once()

    @patch("bootstrap_secrets.getpass.getpass", return_value="hidden-value")
    def test_sensitive_uses_getpass(self, mock_getpass):
        value = bootstrap_secrets.prompt_for_value("some-key", {"description": "d", "sensitive": True})
        self.assertEqual(value, "hidden-value")
        mock_getpass.assert_called_once()

    @patch("builtins.input", return_value="")
    def test_allow_blank_accepts_empty_string_immediately(self, mock_input):
        value = bootstrap_secrets.prompt_for_value("some-key", {"description": "d", "allow_blank": True})
        self.assertEqual(value, "")
        mock_input.assert_called_once()

    @patch("builtins.input", side_effect=["", "", "real-value"])
    def test_non_blank_required_reprompts_until_a_value_is_given(self, mock_input):
        value = bootstrap_secrets.prompt_for_value("some-key", {"description": "d"})
        self.assertEqual(value, "real-value")
        self.assertEqual(mock_input.call_count, 3)


class MainDomainTests(SecretsDirTestCase):
    def test_raises_system_exit_when_missing(self):
        with self.assertRaises(SystemExit):
            bootstrap_secrets._main_domain()

    def test_raises_system_exit_when_blank(self):
        self.seed("main-domain", "   ")
        with self.assertRaises(SystemExit):
            bootstrap_secrets._main_domain()

    def test_returns_stripped_value(self):
        self.seed("main-domain", "  example.com  \n")
        self.assertEqual(bootstrap_secrets._main_domain(), "example.com")


class OpenbaoBaseUrlTests(SecretsDirTestCase):
    def test_url_derives_from_main_domain(self):
        self.seed("main-domain", "example.com")
        # sec.lan.<main_domain> mirrors host_vars/security.yaml +
        # group_vars/all/main.yaml's real naming convention — see this
        # function's own comment for why it's duplicated here rather
        # than templated through Ansible.
        self.assertEqual(bootstrap_secrets._openbao_base_url(), "https://openbao.sec.lan.example.com:8200")


class SecurityCredentialsSshTargetTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")
        self.inventory_tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.inventory_tmp, ignore_errors=True))
        self.inventory_path = self.inventory_tmp / "inventory.yaml"
        patcher = patch.object(bootstrap_secrets, "INVENTORY_PATH", self.inventory_path)
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
        user, host, key_path = bootstrap_secrets._security_ssh_target()
        self.assertEqual(user, "someadmin")
        self.assertEqual(host, "security.internal.example.com")
        self.assertEqual(key_path, str(Path("~/.ssh/some_key").expanduser()))


class FetchRootCertTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")
        patcher = patch.object(
            bootstrap_secrets,
            "_security_ssh_target",
            return_value=("secadmin", "security.internal.example.com", "/home/x/.ssh/key"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("bootstrap_secrets.subprocess.run")
    def test_returns_stdout_on_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="-----BEGIN CERTIFICATE-----\n...", stderr="")
        cert = bootstrap_secrets.fetch_root_cert()
        self.assertIn("BEGIN CERTIFICATE", cert)

    @patch("bootstrap_secrets.subprocess.run")
    def test_uses_ssh_with_the_correct_container_and_command(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="cert", stderr="")
        bootstrap_secrets.fetch_root_cert()
        argv = mock_run.call_args.args[0]
        self.assertEqual(argv[0], "ssh")
        self.assertIn("secadmin@security.internal.example.com", argv)
        self.assertIn(bootstrap_secrets.VAULT_STEP_CA_CONTAINER, argv)
        self.assertEqual(argv[-2:], ["cat", "/home/step/certs/root_ca.crt"])

    @patch("bootstrap_secrets.subprocess.run")
    def test_raises_system_exit_on_nonzero_returncode(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Permission denied")
        with self.assertRaises(SystemExit):
            bootstrap_secrets.fetch_root_cert()


class VaultLoginTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")

    def test_raises_system_exit_when_role_id_missing(self):
        self.seed("openbao-controller-secret-id", "some-secret-id")
        with self.assertRaises(SystemExit):
            bootstrap_secrets.vault_login("/dev/null")

    def test_raises_system_exit_when_secret_id_blank(self):
        self.seed("openbao-controller-role-id", "some-role-id")
        self.seed("openbao-controller-secret-id", "   ")
        with self.assertRaises(SystemExit):
            bootstrap_secrets.vault_login("/dev/null")

    @patch("bootstrap_secrets.requests.post")
    def test_returns_client_token_on_success(self, mock_post):
        self.seed("openbao-controller-role-id", "some-role-id")
        self.seed("openbao-controller-secret-id", "some-secret-id")
        mock_post.return_value = _mock_response(200, {"auth": {"client_token": "s.abc123"}})

        token = bootstrap_secrets.vault_login("/path/to/ca.crt")

        self.assertEqual(token, "s.abc123")
        mock_post.assert_called_once_with(
            "https://openbao.sec.lan.example.com:8200/v1/auth/approle/login",
            json={"role_id": "some-role-id", "secret_id": "some-secret-id"},
            verify="/path/to/ca.crt",
            timeout=10,
        )

    @patch("bootstrap_secrets.requests.post")
    def test_strips_whitespace_from_role_and_secret_id(self, mock_post):
        self.seed("openbao-controller-role-id", "  some-role-id  \n")
        self.seed("openbao-controller-secret-id", "  some-secret-id  \n")
        mock_post.return_value = _mock_response(200, {"auth": {"client_token": "s.abc123"}})

        bootstrap_secrets.vault_login("/path/to/ca.crt")

        sent_json = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_json, {"role_id": "some-role-id", "secret_id": "some-secret-id"})


class VaultReadWriteTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")

    @patch("bootstrap_secrets.requests.get")
    def test_read_returns_none_on_404(self, mock_get):
        mock_get.return_value = _mock_response(404)
        self.assertIsNone(bootstrap_secrets.vault_read("token", "/ca.crt", "hosts/security/some-key"))

    @patch("bootstrap_secrets.requests.get")
    def test_read_returns_value_on_200(self, mock_get):
        mock_get.return_value = _mock_response(200, {"data": {"data": {"value": "the-value"}}})
        value = bootstrap_secrets.vault_read("token", "/ca.crt", "hosts/security/some-key")
        self.assertEqual(value, "the-value")

    @patch("bootstrap_secrets.requests.get")
    def test_read_uses_the_correct_url_and_token_header(self, mock_get):
        mock_get.return_value = _mock_response(200, {"data": {"data": {"value": "x"}}})
        bootstrap_secrets.vault_read("s.abc123", "/ca.crt", "hosts/all/telegram/telegram-token")
        mock_get.assert_called_once_with(
            f"https://openbao.sec.lan.example.com:8200/v1/{bootstrap_secrets.VAULT_KV_MOUNT}/data/hosts/all/telegram/telegram-token",
            headers={"X-Vault-Token": "s.abc123"},
            verify="/ca.crt",
            timeout=10,
        )

    @patch("bootstrap_secrets.requests.get")
    def test_read_raises_on_non_404_error_status(self, mock_get):
        mock_get.return_value = _mock_response(500)
        with self.assertRaises(requests.exceptions.HTTPError):
            bootstrap_secrets.vault_read("token", "/ca.crt", "hosts/security/some-key")

    @patch("bootstrap_secrets.requests.post")
    def test_write_posts_the_correct_payload(self, mock_post):
        mock_post.return_value = _mock_response(200)
        bootstrap_secrets.vault_write("s.abc123", "/ca.crt", "hosts/security/some-key", "the-value")
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"], {"X-Vault-Token": "s.abc123"})
        self.assertEqual(kwargs["json"], {"data": {"value": "the-value"}})
        self.assertEqual(kwargs["verify"], "/ca.crt")

    @patch("bootstrap_secrets.requests.post")
    def test_write_raises_on_error_status(self, mock_post):
        mock_post.return_value = _mock_response(400)
        with self.assertRaises(requests.exceptions.HTTPError):
            bootstrap_secrets.vault_write("token", "/ca.crt", "hosts/security/some-key", "value")


class MainNoRegistryTests(unittest.TestCase):
    @patch.object(bootstrap_secrets, "REGISTRY_PATH", Path("/does/not/exist/secrets_registry.yaml"))
    def test_returns_1_when_registry_missing(self):
        self.assertEqual(bootstrap_secrets.main(), 1)


class MainFileEntriesTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.registry_tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.registry_tmp, ignore_errors=True))
        self.registry_path = self.registry_tmp / "secrets_registry.yaml"
        patcher = patch.object(bootstrap_secrets, "REGISTRY_PATH", self.registry_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_registry(self, content: str) -> None:
        self.registry_path.write_text(content)

    def test_no_manual_entries_returns_0_without_touching_the_filesystem(self):
        self.write_registry("secrets_registry:\n  some-hex: { format: hex, length: 32 }\n")
        self.assertEqual(bootstrap_secrets.main(), 0)
        self.assertFalse(any(self.tmp.iterdir()), "SECRETS_DIR should never be created when there's nothing manual to do")

    @patch("bootstrap_secrets.prompt_for_value", return_value="a-typed-value")
    def test_creates_a_missing_file_entry(self, mock_prompt):
        self.write_registry("secrets_registry:\n  digitalocean-api-key: { format: manual, sensitive: true }\n")
        self.assertEqual(bootstrap_secrets.main(), 0)
        self.assertEqual((self.tmp / "digitalocean-api-key").read_text(), "a-typed-value")
        mode = (self.tmp / "digitalocean-api-key").stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    @patch("bootstrap_secrets.prompt_for_value")
    def test_skips_an_already_present_file_entry_without_prompting(self, mock_prompt):
        self.write_registry("secrets_registry:\n  digitalocean-api-key: { format: manual, sensitive: true }\n")
        self.seed("digitalocean-api-key", "already-set")
        self.assertEqual(bootstrap_secrets.main(), 0)
        mock_prompt.assert_not_called()
        self.assertEqual((self.tmp / "digitalocean-api-key").read_text(), "already-set")

    @patch("bootstrap_secrets.prompt_for_value", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt_during_prompt_returns_1(self, mock_prompt):
        self.write_registry("secrets_registry:\n  digitalocean-api-key: { format: manual, sensitive: true }\n")
        self.assertEqual(bootstrap_secrets.main(), 1)
        self.assertFalse((self.tmp / "digitalocean-api-key").exists())


class MainVaultEntriesTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.registry_tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.registry_tmp, ignore_errors=True))
        self.registry_path = self.registry_tmp / "secrets_registry.yaml"
        self.registry_path.write_text("secrets_registry:\n  telegram-token: { format: manual, sensitive: true, vault_scope: hosts/all/telegram }\n")
        patcher = patch.object(bootstrap_secrets, "REGISTRY_PATH", self.registry_path)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.seed("main-domain", "example.com")
        self.seed("openbao-controller-role-id", "some-role-id")
        self.seed("openbao-controller-secret-id", "some-secret-id")

        fetch_patcher = patch.object(bootstrap_secrets, "fetch_root_cert", return_value="fake-root-cert")
        fetch_patcher.start()
        self.addCleanup(fetch_patcher.stop)

        login_patcher = patch.object(bootstrap_secrets, "vault_login", return_value="s.abc123")
        login_patcher.start()
        self.addCleanup(login_patcher.stop)

    @patch("bootstrap_secrets.vault_write")
    @patch("bootstrap_secrets.vault_read", return_value=None)
    @patch("bootstrap_secrets.prompt_for_value", return_value="a-telegram-token")
    def test_creates_a_missing_vault_entry(self, mock_prompt, mock_read, mock_write):
        self.assertEqual(bootstrap_secrets.main(), 0)
        mock_write.assert_called_once()
        token, ca_path, vault_path, value = mock_write.call_args.args
        self.assertEqual(token, "s.abc123")
        self.assertTrue(ca_path, "ca_path should be a real temp-file path, not empty/None")
        self.assertEqual(vault_path, "hosts/all/telegram/telegram-token")
        self.assertEqual(value, "a-telegram-token")

    @patch("bootstrap_secrets.vault_write")
    @patch("bootstrap_secrets.vault_read", return_value="already-there")
    @patch("bootstrap_secrets.prompt_for_value")
    def test_skips_an_already_present_vault_entry_without_prompting_or_writing(self, mock_prompt, mock_read, mock_write):
        self.assertEqual(bootstrap_secrets.main(), 0)
        mock_prompt.assert_not_called()
        mock_write.assert_not_called()

    @patch("bootstrap_secrets.vault_write")
    @patch("bootstrap_secrets.vault_read", return_value=None)
    def test_temp_ca_file_is_removed_after_use(self, mock_read, mock_write):
        written_paths = []
        mock_write.side_effect = lambda token, ca_path, vault_path, value: written_paths.append(ca_path)

        with patch("bootstrap_secrets.prompt_for_value", return_value="x"):
            bootstrap_secrets.main()

        self.assertEqual(len(written_paths), 1)
        self.assertFalse(Path(written_paths[0]).exists(), "temp CA file should be cleaned up after main() returns")

    @patch("bootstrap_secrets.vault_write")
    @patch("bootstrap_secrets.vault_read", return_value=None)
    @patch("bootstrap_secrets.prompt_for_value", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt_during_vault_prompt_returns_1_and_does_not_write(self, mock_prompt, mock_read, mock_write):
        self.assertEqual(bootstrap_secrets.main(), 1)
        mock_write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
