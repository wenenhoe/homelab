"""Unit tests for bootstrap_secrets.py.

Run via `uv run pytest ansible/tests/ -v`. Every SSH/Vault call is
mocked; nothing here touches a real `security` host or a real OpenBao.
fetch_root_cert/vault_read/vault_write/the bare vault_login are
openbao_client.client's own functions (imported directly, some
re-exported under the same name) - tested once, directly, in
tools/tests/openbao_client/test_client.py. This file only tests
bootstrap_secrets.py's own remaining logic: the registry/prompt
handling, its own vault_login wrapper, and main()'s wiring.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bootstrap_secrets
from openbao_client import client as openbao_client_module


class SecretsDirTestCase(unittest.TestCase):
    """Base for anything touching SECRETS_DIR — every Vault/inventory test
    also needs this, since main_domain/role_id/secret_id are always read
    from here regardless of which path is under test. Patches both
    bootstrap_secrets' own imported SECRETS_DIR (used directly by
    main()/read_cache_file) and openbao_client.client's own copy (used
    internally by read_bootstrap_file(), which this file's vault_login
    wrapper calls) - both need to agree, since they're two separate
    names bound to what was originally the same object at import time.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(bootstrap_secrets, "SECRETS_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        shared_patcher = patch.object(openbao_client_module, "SECRETS_DIR", self.tmp)
        shared_patcher.start()
        self.addCleanup(shared_patcher.stop)

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

    def test_load_manual_entries_excludes_cloud_credential_owned_names(self):
        # cloudflare-r2-write-access-key is a real LEGACY_CACHE_KEYS name
        # (create_leaf_keys.py/create_rotation_keys.py's own concern, per
        # this script's module docstring) — even with format: manual and a
        # vault_scope, it must never reach this script's prompt-and-write
        # path.
        self.write_registry(
            "secrets_registry:\n  main-domain: { format: manual }\n  cloudflare-r2-write-access-key: { format: manual, vault_scope: cloud_credentials/leaf }\n"
        )
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


class VaultLoginTests(SecretsDirTestCase):
    """bootstrap_secrets.vault_login is just the role_id/secret_id
    file-reading and validation wrapper around openbao_client.client's
    shared bare vault_login - see that module's own tests for the
    login call itself."""

    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")

    def test_raises_system_exit_when_role_id_missing(self):
        self.seed("openbao-controller-secret-id", "some-secret-id")
        with self.assertRaises(SystemExit):
            bootstrap_secrets.vault_login(MagicMock())

    def test_raises_system_exit_when_secret_id_blank(self):
        self.seed("openbao-controller-role-id", "some-role-id")
        self.seed("openbao-controller-secret-id", "   ")
        with self.assertRaises(SystemExit):
            bootstrap_secrets.vault_login(MagicMock())

    @patch("bootstrap_secrets._bare_vault_login")
    def test_calls_bare_login_with_role_id_and_secret_id(self, mock_bare_login):
        self.seed("openbao-controller-role-id", "some-role-id")
        self.seed("openbao-controller-secret-id", "some-secret-id")
        mock_client = MagicMock()

        bootstrap_secrets.vault_login(mock_client)

        mock_bare_login.assert_called_once_with(mock_client, "some-role-id", "some-secret-id")


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

        login_patcher = patch.object(bootstrap_secrets, "vault_login")
        login_patcher.start()
        self.addCleanup(login_patcher.stop)

    @patch("bootstrap_secrets.vault_write")
    @patch("bootstrap_secrets.vault_read", return_value=None)
    @patch("bootstrap_secrets.prompt_for_value", return_value="a-telegram-token")
    def test_creates_a_missing_vault_entry(self, mock_prompt, mock_read, mock_write):
        self.assertEqual(bootstrap_secrets.main(), 0)
        mock_write.assert_called_once()
        client_arg, vault_path, value = mock_write.call_args.args
        self.assertEqual(vault_path, "hosts/all/telegram/telegram-token")
        self.assertEqual(value, "a-telegram-token")
        # One hvac.Client built and threaded through login/read/write -
        # not reconstructed per call.
        self.assertIs(bootstrap_secrets.vault_login.call_args.args[0], client_arg)
        self.assertIs(mock_read.call_args.args[0], client_arg)

    @patch("bootstrap_secrets.vault_write")
    @patch("bootstrap_secrets.vault_read", return_value="already-there")
    @patch("bootstrap_secrets.prompt_for_value")
    def test_skips_an_already_present_vault_entry_without_prompting_or_writing(self, mock_prompt, mock_read, mock_write):
        self.assertEqual(bootstrap_secrets.main(), 0)
        mock_prompt.assert_not_called()
        mock_write.assert_not_called()

    @patch("bootstrap_secrets.hvac.Client")
    @patch("bootstrap_secrets.vault_write")
    @patch("bootstrap_secrets.vault_read", return_value=None)
    @patch("bootstrap_secrets.prompt_for_value", return_value="x")
    def test_temp_ca_file_is_removed_after_use(self, mock_prompt, mock_read, mock_write, mock_client_cls):
        bootstrap_secrets.main()
        ca_path = mock_client_cls.call_args.kwargs["verify"]
        self.assertTrue(ca_path, "ca_path should be a real temp-file path, not empty/None")
        self.assertFalse(Path(ca_path).exists(), "temp CA file should be cleaned up after main() returns")

    @patch("bootstrap_secrets.vault_write")
    @patch("bootstrap_secrets.vault_read", return_value=None)
    @patch("bootstrap_secrets.prompt_for_value", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt_during_vault_prompt_returns_1_and_does_not_write(self, mock_prompt, mock_read, mock_write):
        self.assertEqual(bootstrap_secrets.main(), 1)
        mock_write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
