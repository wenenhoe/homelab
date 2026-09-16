"""Unit tests for openbao_utils.restore.

Run via `uv run pytest tools/tests/ -v`. Fake Vault reads/writes, a
real tmp filesystem for the backup dir and registry file - no real
Vault. Covers both phases this script merges: registry-scoped restore
(via read_vault_path/write_vault_path) and LEGACY_CACHE_KEYS restore
(via each key's own module double). Each phase's own tests neutralize
the *other* phase (an empty LEGACY_CACHE_KEYS list, or an empty
registry) rather than mocking it away - main() runs both phases
unconditionally, so leaving the other phase's real dependencies
wired up would mean an unmocked real Vault session gets built.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

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


class UsageErrorTests(unittest.TestCase):
    """main()'s usage/directory checks happen before either phase
    runs, so these don't need either phase mocked."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def test_usage_error_when_no_directory_given(self):
        with patch.object(sys, "argv", ["restore.py"]):
            rc = restore.main()
        self.assertEqual(rc, 1)

    def test_error_when_given_path_is_not_a_directory(self):
        with patch.object(sys, "argv", ["restore.py", str(self.tmp / "does-not-exist")]):
            rc = restore.main()
        self.assertEqual(rc, 1)


class RegistryScopedRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.registry_file = self.tmp / "registry.yaml"
        self.backup_dir = self.tmp / "backup"
        self.backup_dir.mkdir()
        patch.object(restore, "REGISTRY_PATH", self.registry_file).start()
        # Neutralizes the other phase - an empty list means its for
        # loop never iterates, never touching a real Vault session.
        patch.object(restore, "LEGACY_CACHE_KEYS", []).start()
        self.addCleanup(patch.stopall)

    def _seed_registry(self, text: str) -> None:
        self.registry_file.write_text(text)

    def test_restores_a_value_present_in_the_backup_but_not_in_vault(self):
        self._seed_registry("secrets_registry:\n  lldap-jwt-secret:\n    format: hex\n    vault_scope: hosts/security\n")
        (self.backup_dir / "lldap-jwt-secret").write_text("the-old-jwt-secret")

        written = {}
        with (
            patch.object(restore, "read_vault_path", return_value=None),
            patch.object(restore, "write_vault_path", side_effect=lambda path, value: written.__setitem__(path, value)),
        ):
            rc = _run(self.backup_dir)

        self.assertEqual(rc, 0)
        self.assertEqual(written, {"hosts/security/lldap-jwt-secret": "the-old-jwt-secret"})

    def test_never_overwrites_a_value_already_in_vault(self):
        self._seed_registry("secrets_registry:\n  lldap-jwt-secret:\n    format: hex\n    vault_scope: hosts/security\n")
        (self.backup_dir / "lldap-jwt-secret").write_text("stale-backup-value")

        with (
            patch.object(restore, "read_vault_path", return_value="already-there"),
            patch.object(restore, "write_vault_path") as fake_write,
        ):
            rc = _run(self.backup_dir)

        self.assertEqual(rc, 0)
        fake_write.assert_not_called()

    def test_entry_missing_from_the_backup_is_reported_not_written(self):
        self._seed_registry("secrets_registry:\n  never-backed-up:\n    format: manual\n    vault_scope: hosts/services\n")

        with (
            patch.object(restore, "read_vault_path", return_value=None),
            patch.object(restore, "write_vault_path") as fake_write,
        ):
            rc = _run(self.backup_dir)

        self.assertEqual(rc, 0)
        fake_write.assert_not_called()

    def test_skips_entries_without_a_vault_scope(self):
        self._seed_registry("secrets_registry:\n  no-scope-key:\n    format: manual\n")
        (self.backup_dir / "no-scope-key").write_text("value")

        with (
            patch.object(restore, "read_vault_path", return_value=None),
            patch.object(restore, "write_vault_path") as fake_write,
        ):
            rc = _run(self.backup_dir)

        self.assertEqual(rc, 0)
        fake_write.assert_not_called()

    def test_restores_backup_content_byte_for_byte_not_stripped(self):
        # Regression test for the bug found on merge: the other phase
        # (LEGACY_CACHE_KEYS) used to strip() backup content before
        # this merge - openbao_utils/dump.py writes the raw
        # value with no added whitespace, so stripping on the way back
        # in would silently corrupt a value with meaningful
        # leading/trailing whitespace.
        self._seed_registry("secrets_registry:\n  padded-value:\n    format: manual\n    vault_scope: hosts/services\n")
        (self.backup_dir / "padded-value").write_text("  has padding  \n")

        written = {}
        with (
            patch.object(restore, "read_vault_path", return_value=None),
            patch.object(restore, "write_vault_path", side_effect=lambda path, value: written.__setitem__(path, value)),
        ):
            _run(self.backup_dir)

        self.assertEqual(written["hosts/services/padded-value"], "  has padding  \n")


class LegacyCacheKeysRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.registry_file = self.tmp / "registry.yaml"
        # Neutralizes the other phase - an empty registry means
        # _scoped_registry_entries() returns {}, never touching a real
        # Vault session via read_vault_path/write_vault_path.
        self.registry_file.write_text("secrets_registry: {}\n")
        patch.object(restore, "REGISTRY_PATH", self.registry_file).start()
        self.addCleanup(patch.stopall)

    def seed_backup_file(self, name: str, value: str) -> None:
        (self.tmp / name).write_text(value)

    def test_restores_a_key_present_in_backup_but_not_vault(self):
        mod = _FakeModule()
        self.seed_backup_file("some-key", "the-value")
        with patch.object(restore, "LEGACY_CACHE_KEYS", [("some-key", mod)]):
            rc = _run(self.tmp)
        self.assertEqual(rc, 0)
        self.assertEqual(mod.store["some-key"], "the-value")

    def test_skips_a_key_already_present_in_vault_without_overwriting(self):
        mod = _FakeModule()
        mod.store["some-key"] = "vault-value"
        self.seed_backup_file("some-key", "backup-value")
        with patch.object(restore, "LEGACY_CACHE_KEYS", [("some-key", mod)]):
            _run(self.tmp)
        self.assertEqual(mod.store["some-key"], "vault-value")

    def test_key_with_no_backup_file_is_left_alone(self):
        mod = _FakeModule()
        with patch.object(restore, "LEGACY_CACHE_KEYS", [("some-key", mod)]):
            rc = _run(self.tmp)
        self.assertEqual(rc, 0)
        self.assertNotIn("some-key", mod.store)

    def test_multiple_keys_are_handled_independently(self):
        mod_a, mod_b = _FakeModule(), _FakeModule()
        self.seed_backup_file("key-a", "value-a")
        # key-b deliberately has no backup file.
        with patch.object(restore, "LEGACY_CACHE_KEYS", [("key-a", mod_a), ("key-b", mod_b)]):
            _run(self.tmp)
        self.assertEqual(mod_a.store.get("key-a"), "value-a")
        self.assertNotIn("key-b", mod_b.store)

    def test_restores_backup_content_byte_for_byte_not_stripped(self):
        # Regression test for the bug found on merge - see the
        # matching test in RegistryScopedRestoreTests for the full
        # explanation.
        mod = _FakeModule()
        self.seed_backup_file("padded-key", "  has padding  \n")
        with patch.object(restore, "LEGACY_CACHE_KEYS", [("padded-key", mod)]):
            _run(self.tmp)
        self.assertEqual(mod.store["padded-key"], "  has padding  \n")


if __name__ == "__main__":
    unittest.main()
