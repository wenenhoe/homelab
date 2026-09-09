"""Unit tests for restore_cloud_credentials_from_backup.

Run via `uv run pytest ansible/tests/ -v`. Exercises main()'s own
restore/skip logic against a fake module double, not the real
leaf_keys/rotation_keys modules or a real Vault - the Vault plumbing
behind cached()/write_cache() is already covered by test_cache.py.
Adapted from the retired migrate_legacy_cache_to_vault.py's own test
(same logic, source is now a given backup directory, not
ansible/files/secrets/).
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import restore_cloud_credentials_from_backup as restore


class _FakeModule:
    """Minimal stand-in for a leaf_keys/rotation_keys module - just the
    two functions main() actually calls, backed by an in-memory dict."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def cached(self, name: str) -> bool:
        return name in self.store

    def write_cache(self, name: str, value: str) -> None:
        self.store[name] = value


def _run(backup_dir: Path) -> int:
    with patch.object(sys, "argv", ["restore_cloud_credentials_from_backup.py", str(backup_dir)]):
        return restore.main()


class RestoreCloudCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def seed_backup_file(self, name: str, value: str) -> None:
        (self.tmp / name).write_text(value)

    def test_usage_error_when_no_directory_given(self):
        with patch.object(sys, "argv", ["restore_cloud_credentials_from_backup.py"]):
            rc = restore.main()
        self.assertEqual(rc, 1)

    def test_error_when_given_path_is_not_a_directory(self):
        with patch.object(sys, "argv", ["restore_cloud_credentials_from_backup.py", str(self.tmp / "does-not-exist")]):
            rc = restore.main()
        self.assertEqual(rc, 1)

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


if __name__ == "__main__":
    unittest.main()
