"""Unit tests for openbao_utils.restore.

Run via `uv run pytest tools/tests/ -v`. Fake Vault reads/writes, a
real tmp filesystem for the backup dir and catalog file - no real
Vault. Covers both phases this script merges: catalog-scoped restore
(via read_vault_path/write_vault_path) and LEGACY_CACHE_KEYS restore
(via each key's own module double). Each phase's own tests neutralize
the *other* phase (an empty LEGACY_CACHE_KEYS list, or an empty
catalog) rather than mocking it away - main() runs both phases
unconditionally, so leaving the other phase's real dependencies
wired up would mean an unmocked real Vault session gets built.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from openbao_utils import restore


def _run(backup_dir: Path) -> int:
    with patch.object(sys, "argv", ["restore.py", str(backup_dir)]):
        return restore.main()


class _FakeModule:
    """Minimal stand-in for a leaf_keys/rotation_keys module - just the
    two functions main() actually calls, backed by an in-memory dict."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def cached(self, name: str) -> bool:
        return name in self.store

    def write_cache(self, name: str, value: str) -> None:
        self.store[name] = value


@pytest.fixture
def tmp(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("restore")


class TestUsageError:
    """main()'s usage/directory checks happen before either phase
    runs, so these don't need either phase mocked."""

    def test_usage_error_when_no_directory_given(self):
        with patch.object(sys, "argv", ["restore.py"]):
            rc = restore.main()
        assert rc == 1

    def test_error_when_given_path_is_not_a_directory(self, tmp):
        with patch.object(sys, "argv", ["restore.py", str(tmp / "does-not-exist")]):
            rc = restore.main()
        assert rc == 1


class TestCatalogScopedRestore:
    @pytest.fixture(autouse=True)
    def env(self, tmp, monkeypatch) -> SimpleNamespace:
        catalog_file = tmp / "catalog.yaml"
        backup_dir = tmp / "backup"
        backup_dir.mkdir()
        monkeypatch.setattr(restore, "CATALOG_PATH", catalog_file)
        # Neutralizes the other phase - an empty list means its for
        # loop never iterates, never touching a real Vault session.
        monkeypatch.setattr(restore, "LEGACY_CACHE_KEYS", [])
        return SimpleNamespace(catalog_file=catalog_file, backup_dir=backup_dir)

    def test_restores_a_value_present_in_the_backup_but_not_in_vault(self, env):
        env.catalog_file.write_text("secret_catalog:\n  lldap-jwt-secret:\n    source: hex\n    store: openbao\n    scope: hosts/security\n")
        (env.backup_dir / "lldap-jwt-secret").write_text("the-old-jwt-secret")

        written = {}
        with (
            patch.object(restore, "read_vault_path", return_value=None, autospec=True),
            patch.object(restore, "write_vault_path", side_effect=lambda path, value: written.__setitem__(path, value), autospec=True),
        ):
            rc = _run(env.backup_dir)

        assert rc == 0
        assert written == {"hosts/security/lldap-jwt-secret": "the-old-jwt-secret"}

    def test_never_overwrites_a_value_already_in_vault(self, env):
        env.catalog_file.write_text("secret_catalog:\n  lldap-jwt-secret:\n    source: hex\n    store: openbao\n    scope: hosts/security\n")
        (env.backup_dir / "lldap-jwt-secret").write_text("stale-backup-value")

        with (
            patch.object(restore, "read_vault_path", return_value="already-there", autospec=True),
            patch.object(restore, "write_vault_path", autospec=True) as fake_write,
        ):
            rc = _run(env.backup_dir)

        assert rc == 0
        fake_write.assert_not_called()

    def test_entry_missing_from_the_backup_is_reported_not_written(self, env):
        env.catalog_file.write_text("secret_catalog:\n  never-backed-up:\n    source: manual\n    store: openbao\n    scope: hosts/services\n")

        with (
            patch.object(restore, "read_vault_path", return_value=None, autospec=True),
            patch.object(restore, "write_vault_path", autospec=True) as fake_write,
        ):
            rc = _run(env.backup_dir)

        assert rc == 0
        fake_write.assert_not_called()

    def test_skips_entries_stored_in_the_file_cache(self, env):
        env.catalog_file.write_text("secret_catalog:\n  no-scope-key:\n    source: manual\n    store: controller_file\n")
        (env.backup_dir / "no-scope-key").write_text("value")

        with (
            patch.object(restore, "read_vault_path", return_value=None, autospec=True),
            patch.object(restore, "write_vault_path", autospec=True) as fake_write,
        ):
            rc = _run(env.backup_dir)

        assert rc == 0
        fake_write.assert_not_called()

    def test_restores_backup_content_byte_for_byte_not_stripped(self, env):
        # The other phase (LEGACY_CACHE_KEYS) must not strip() backup
        # content before this merge - openbao_utils/dump.py writes the raw
        # value with no added whitespace, so stripping on the way back
        # in would silently corrupt a value with meaningful
        # leading/trailing whitespace.
        env.catalog_file.write_text("secret_catalog:\n  padded-value:\n    source: manual\n    store: openbao\n    scope: hosts/services\n")
        (env.backup_dir / "padded-value").write_text("  has padding  \n")

        written = {}
        with (
            patch.object(restore, "read_vault_path", return_value=None, autospec=True),
            patch.object(restore, "write_vault_path", side_effect=lambda path, value: written.__setitem__(path, value), autospec=True),
        ):
            _run(env.backup_dir)

        assert written["hosts/services/padded-value"] == "  has padding  \n"


class TestLegacyCacheKeysRestore:
    @pytest.fixture(autouse=True)
    def _empty_catalog(self, tmp, monkeypatch):
        catalog_file = tmp / "catalog.yaml"
        # Neutralizes the other phase - an empty catalog means
        # _scoped_catalog_entries() returns {}, never touching a real
        # Vault session via read_vault_path/write_vault_path.
        catalog_file.write_text("secret_catalog: {}\n")
        monkeypatch.setattr(restore, "CATALOG_PATH", catalog_file)

    @staticmethod
    def seed_backup_file(tmp: Path, name: str, value: str) -> None:
        (tmp / name).write_text(value)

    def test_restores_a_key_present_in_backup_but_not_vault(self, tmp):
        mod = _FakeModule()
        self.seed_backup_file(tmp, "some-key", "the-value")
        with patch.object(restore, "LEGACY_CACHE_KEYS", [("some-key", mod)]):
            rc = _run(tmp)
        assert rc == 0
        assert mod.store["some-key"] == "the-value"

    def test_skips_a_key_already_present_in_vault_without_overwriting(self, tmp):
        mod = _FakeModule()
        mod.store["some-key"] = "vault-value"
        self.seed_backup_file(tmp, "some-key", "backup-value")
        with patch.object(restore, "LEGACY_CACHE_KEYS", [("some-key", mod)]):
            _run(tmp)
        assert mod.store["some-key"] == "vault-value"

    def test_key_with_no_backup_file_is_left_alone(self, tmp):
        mod = _FakeModule()
        with patch.object(restore, "LEGACY_CACHE_KEYS", [("some-key", mod)]):
            rc = _run(tmp)
        assert rc == 0
        assert "some-key" not in mod.store

    def test_multiple_keys_are_handled_independently(self, tmp):
        mod_a, mod_b = _FakeModule(), _FakeModule()
        self.seed_backup_file(tmp, "key-a", "value-a")
        # key-b deliberately has no backup file.
        with patch.object(restore, "LEGACY_CACHE_KEYS", [("key-a", mod_a), ("key-b", mod_b)]):
            _run(tmp)
        assert mod_a.store.get("key-a") == "value-a"
        assert "key-b" not in mod_b.store

    def test_restores_backup_content_byte_for_byte_not_stripped(self, tmp):
        # See the matching test in CatalogScopedRestoreTests for the
        # full explanation.
        mod = _FakeModule()
        self.seed_backup_file(tmp, "padded-key", "  has padding  \n")
        with patch.object(restore, "LEGACY_CACHE_KEYS", [("padded-key", mod)]):
            _run(tmp)
        assert mod.store["padded-key"] == "  has padding  \n"
