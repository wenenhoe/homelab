"""Unit tests for openbao_utils.bootstrap.

Run via `uv run pytest tools/tests/ -v`. Every SSH/Vault call is
mocked; nothing here touches a real `security` host or a real OpenBao.
fetch_root_cert/vault_read/vault_write/the bare vault_login are
openbao_utils.client's own functions (imported directly, some
re-exported under the same name) - tested once, directly, in
tools/tests/openbao_utils/test_client.py. This file only tests
bootstrap.py's own remaining logic: the catalog/prompt handling, its
own vault_login wrapper, and main()'s wiring.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from openbao_utils import bootstrap


@pytest.fixture
def secrets_dir(secrets_dir, monkeypatch):
    """Every Vault/inventory test also needs SECRETS_DIR, since
    main_domain/role_id/secret_id are always read from here regardless
    of which path is under test. The shared fixture patches utils.repo's
    own copy (used internally by read_bootstrap_file(), which this file's
    vault_login wrapper calls); this also patches bootstrap' own imported
    SECRETS_DIR (used directly by main()/read_cache_file) - both need to
    agree, since they're two separate names bound to what was originally
    the same object at import time.
    """
    monkeypatch.setattr(bootstrap, "SECRETS_DIR", secrets_dir.path)
    return secrets_dir


@pytest.fixture
def catalog_path(tmp_path_factory: pytest.TempPathFactory, monkeypatch) -> Path:
    path = tmp_path_factory.mktemp("catalog") / "secret_catalog.yaml"
    monkeypatch.setattr(bootstrap, "CATALOG_PATH", path)
    return path


class TestCatalogLoading:
    def test_load_catalog_returns_the_secret_catalog_key(self, catalog_path):
        catalog_path.write_text("secret_catalog:\n  main-domain: { source: manual, store: controller_file }\n")
        assert bootstrap.load_catalog(bootstrap.CATALOG_PATH) == {"main-domain": {"source": "manual", "store": "controller_file"}}

    def test_load_manual_entries_excludes_hex_and_uuid4(self, catalog_path):
        catalog_path.write_text(
            "secret_catalog:\n"
            "  main-domain: { source: manual, store: controller_file }\n"
            "  some-hex: { source: hex, length: 32, store: openbao, scope: hosts/play }\n"
            "  some-uuid: { source: uuid4, store: openbao, scope: hosts/play }\n"
        )
        catalog = bootstrap.load_catalog(bootstrap.CATALOG_PATH)
        manual = bootstrap.load_manual_entries(catalog)
        assert list(manual.keys()) == ["main-domain"]

    def test_load_manual_entries_excludes_cloud_credential_owned_names(self, catalog_path):
        # cloudflare-r2-write-access-key is a real LEGACY_CACHE_KEYS name
        # (create_leaf_keys.py/create_rotation_keys.py's own concern, per
        # this script's module docstring) — even with source: manual and
        # store: openbao, it must never reach this script's prompt-and-write
        # path.
        catalog_path.write_text(
            "secret_catalog:\n"
            "  main-domain: { source: manual, store: controller_file }\n"
            "  cloudflare-r2-write-access-key: { source: manual, store: openbao, scope: cloud_credentials/leaf }\n"
        )
        catalog = bootstrap.load_catalog(bootstrap.CATALOG_PATH)
        manual = bootstrap.load_manual_entries(catalog)
        assert list(manual.keys()) == ["main-domain"]


@pytest.mark.usefixtures("secrets_dir")
class TestReadCacheFile:
    def test_returns_none_when_missing(self):
        assert bootstrap.read_cache_file("does-not-exist") is None

    def test_returns_content_when_present(self, secrets_dir):
        secrets_dir.seed("main-domain", "example.com")
        assert bootstrap.read_cache_file("main-domain") == "example.com"


class TestPromptForValue:
    @patch("builtins.input", return_value="typed-value")
    def test_non_sensitive_uses_input(self, mock_input):
        value = bootstrap.prompt_for_value("some-key", {"description": "d", "sensitive": False})
        assert value == "typed-value"
        mock_input.assert_called_once()

    @patch("openbao_utils.bootstrap.getpass.getpass", return_value="hidden-value")
    def test_sensitive_uses_getpass(self, mock_getpass):
        value = bootstrap.prompt_for_value("some-key", {"description": "d", "sensitive": True})
        assert value == "hidden-value"
        mock_getpass.assert_called_once()

    @patch("builtins.input", return_value="")
    def test_allow_blank_accepts_empty_string_immediately(self, mock_input):
        value = bootstrap.prompt_for_value("some-key", {"description": "d", "allow_blank": True})
        assert value == ""
        mock_input.assert_called_once()

    @patch("builtins.input", side_effect=["", "", "real-value"])
    def test_non_blank_required_reprompts_until_a_value_is_given(self, mock_input):
        value = bootstrap.prompt_for_value("some-key", {"description": "d"})
        assert value == "real-value"
        assert mock_input.call_count == 3


class TestVaultLogin:
    """bootstrap.vault_login is just the role_id/secret_id
    file-reading and validation wrapper around openbao_utils.client's
    shared bare vault_login - see that module's own tests for the
    login call itself."""

    @pytest.fixture(autouse=True)
    def _main_domain(self, secrets_dir):
        secrets_dir.seed("main-domain", "example.com")

    def test_raises_system_exit_when_role_id_missing(self, secrets_dir):
        secrets_dir.seed("openbao-controller-secret-id", "some-secret-id")
        with pytest.raises(SystemExit):
            bootstrap.vault_login(MagicMock())

    def test_raises_system_exit_when_secret_id_blank(self, secrets_dir):
        secrets_dir.seed("openbao-controller-role-id", "some-role-id")
        secrets_dir.seed("openbao-controller-secret-id", "   ")
        with pytest.raises(SystemExit):
            bootstrap.vault_login(MagicMock())

    @patch("openbao_utils.bootstrap._bare_vault_login")
    def test_calls_bare_login_with_role_id_and_secret_id(self, mock_bare_login, secrets_dir):
        secrets_dir.seed("openbao-controller-role-id", "some-role-id")
        secrets_dir.seed("openbao-controller-secret-id", "some-secret-id")
        mock_client = MagicMock()

        bootstrap.vault_login(mock_client)

        mock_bare_login.assert_called_once_with(mock_client, "some-role-id", "some-secret-id")


class TestMainNoCatalog:
    @patch.object(bootstrap, "CATALOG_PATH", Path("/does/not/exist/secret_catalog.yaml"))
    def test_returns_1_when_catalog_missing(self):
        assert bootstrap.main() == 1


@pytest.mark.usefixtures("secrets_dir")
class TestMainFileEntries:
    def test_no_manual_entries_returns_0_without_touching_the_filesystem(self, secrets_dir, catalog_path):
        catalog_path.write_text("secret_catalog:\n  some-hex: { source: hex, length: 32, store: controller_file }\n")
        assert bootstrap.main() == 0
        assert not any(secrets_dir.path.iterdir()), "SECRETS_DIR should never be created when there's nothing manual to do"

    @patch("openbao_utils.bootstrap.prompt_for_value", return_value="a-typed-value")
    def test_creates_a_missing_file_entry(self, mock_prompt, secrets_dir, catalog_path):
        catalog_path.write_text("secret_catalog:\n  digitalocean-api-key: { source: manual, sensitive: true, store: controller_file }\n")
        assert bootstrap.main() == 0
        assert (secrets_dir.path / "digitalocean-api-key").read_text() == "a-typed-value"
        mode = (secrets_dir.path / "digitalocean-api-key").stat().st_mode & 0o777
        assert mode == 0o600

    @patch("openbao_utils.bootstrap.prompt_for_value")
    def test_skips_an_already_present_file_entry_without_prompting(self, mock_prompt, secrets_dir, catalog_path):
        catalog_path.write_text("secret_catalog:\n  digitalocean-api-key: { source: manual, sensitive: true, store: controller_file }\n")
        secrets_dir.seed("digitalocean-api-key", "already-set")
        assert bootstrap.main() == 0
        mock_prompt.assert_not_called()
        assert (secrets_dir.path / "digitalocean-api-key").read_text() == "already-set"

    @patch("openbao_utils.bootstrap.prompt_for_value", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt_during_prompt_returns_1(self, mock_prompt, secrets_dir, catalog_path):
        catalog_path.write_text("secret_catalog:\n  digitalocean-api-key: { source: manual, sensitive: true, store: controller_file }\n")
        assert bootstrap.main() == 1
        assert not (secrets_dir.path / "digitalocean-api-key").exists()


class TestMainVaultEntries:
    @pytest.fixture(autouse=True)
    def _vault_environment(self, secrets_dir, catalog_path, monkeypatch):
        catalog_path.write_text("secret_catalog:\n  telegram-token: { source: manual, sensitive: true, store: openbao, scope: hosts/all/telegram }\n")

        secrets_dir.seed("main-domain", "example.com")
        secrets_dir.seed("openbao-controller-role-id", "some-role-id")
        secrets_dir.seed("openbao-controller-secret-id", "some-secret-id")

        monkeypatch.setattr(bootstrap, "fetch_root_cert", MagicMock(return_value="fake-root-cert"))
        monkeypatch.setattr(bootstrap, "vault_login", MagicMock())

    @patch("openbao_utils.bootstrap.vault_write")
    @patch("openbao_utils.bootstrap.vault_read", return_value=None)
    @patch("openbao_utils.bootstrap.prompt_for_value", return_value="a-telegram-token")
    def test_creates_a_missing_vault_entry(self, mock_prompt, mock_read, mock_write):
        assert bootstrap.main() == 0
        mock_write.assert_called_once()
        client_arg, vault_path, value = mock_write.call_args.args
        assert vault_path == "hosts/all/telegram/telegram-token"
        assert value == "a-telegram-token"
        # One hvac.Client built and threaded through login/read/write -
        # not reconstructed per call.
        assert bootstrap.vault_login.call_args.args[0] is client_arg
        assert mock_read.call_args.args[0] is client_arg

    @patch("openbao_utils.bootstrap.vault_write")
    @patch("openbao_utils.bootstrap.vault_read", return_value="already-there")
    @patch("openbao_utils.bootstrap.prompt_for_value")
    def test_skips_an_already_present_vault_entry_without_prompting_or_writing(self, mock_prompt, mock_read, mock_write):
        assert bootstrap.main() == 0
        mock_prompt.assert_not_called()
        mock_write.assert_not_called()

    @patch("openbao_utils.bootstrap.hvac.Client")
    @patch("openbao_utils.bootstrap.vault_write")
    @patch("openbao_utils.bootstrap.vault_read", return_value=None)
    @patch("openbao_utils.bootstrap.prompt_for_value", return_value="x")
    def test_temp_ca_file_is_removed_after_use(self, mock_prompt, mock_read, mock_write, mock_client_cls):
        bootstrap.main()
        ca_path = mock_client_cls.call_args.kwargs["verify"]
        assert ca_path, "ca_path should be a real temp-file path, not empty/None"
        assert not Path(ca_path).exists(), "temp CA file should be cleaned up after main() returns"

    @patch("openbao_utils.bootstrap.vault_write")
    @patch("openbao_utils.bootstrap.vault_read", return_value=None)
    @patch("openbao_utils.bootstrap.prompt_for_value", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt_during_vault_prompt_returns_1_and_does_not_write(self, mock_prompt, mock_read, mock_write):
        assert bootstrap.main() == 1
        mock_write.assert_not_called()
