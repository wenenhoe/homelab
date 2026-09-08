"""Unit tests for cloud_credentials.migrate_legacy_cache_to_vault.

Run via `uv run pytest ansible/tests/ -v`. Exercises main()'s own
migrate/skip logic against a fake module double, not the real
leaf_keys/rotation_keys modules or a real Vault - the Vault plumbing
behind cached()/write_cache() is already covered by test_cache.py.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cloud_credentials import migrate_legacy_cache_to_vault as migrate


class _FakeModule:
    """Minimal stand-in for a leaf_keys/rotation_keys module - just the
    two functions main() actually calls, backed by an in-memory dict."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def cached(self, name: str) -> bool:
        return name in self.store

    def write_cache(self, name: str, value: str) -> None:
        self.store[name] = value


class MigrateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patch.object(migrate, "SECRETS_DIR", self.tmp).start()
        self.addCleanup(patch.stopall)

    def seed_file(self, name: str, value: str) -> None:
        (self.tmp / name).write_text(value)

    def test_migrates_a_key_present_in_file_cache_but_not_vault(self):
        mod = _FakeModule()
        self.seed_file("some-key", "the-value")
        with patch.object(migrate, "LEGACY_CACHE_KEYS", [("some-key", mod)]):
            rc = migrate.main()
        self.assertEqual(rc, 0)
        self.assertEqual(mod.store["some-key"], "the-value")

    def test_skips_a_key_already_present_in_vault_without_overwriting(self):
        mod = _FakeModule()
        mod.store["some-key"] = "vault-value"
        self.seed_file("some-key", "file-value")
        with patch.object(migrate, "LEGACY_CACHE_KEYS", [("some-key", mod)]):
            migrate.main()
        # Must never overwrite an existing Vault value, even if the file
        # cache disagrees - that's a human decision (audit_vault_state.py
        # is what surfaces the disagreement, not this script's job to fix).
        self.assertEqual(mod.store["some-key"], "vault-value")

    def test_key_with_no_legacy_file_is_left_alone(self):
        mod = _FakeModule()
        with patch.object(migrate, "LEGACY_CACHE_KEYS", [("some-key", mod)]):
            rc = migrate.main()
        self.assertEqual(rc, 0)
        self.assertNotIn("some-key", mod.store)

    def test_never_deletes_the_legacy_file_after_migrating(self):
        mod = _FakeModule()
        self.seed_file("some-key", "the-value")
        with patch.object(migrate, "LEGACY_CACHE_KEYS", [("some-key", mod)]):
            migrate.main()
        self.assertTrue((self.tmp / "some-key").exists())

    def test_multiple_keys_are_handled_independently(self):
        mod_a, mod_b = _FakeModule(), _FakeModule()
        self.seed_file("key-a", "value-a")
        # key-b deliberately has no legacy file.
        with patch.object(migrate, "LEGACY_CACHE_KEYS", [("key-a", mod_a), ("key-b", mod_b)]):
            migrate.main()
        self.assertEqual(mod_a.store.get("key-a"), "value-a")
        self.assertNotIn("key-b", mod_b.store)


if __name__ == "__main__":
    unittest.main()
