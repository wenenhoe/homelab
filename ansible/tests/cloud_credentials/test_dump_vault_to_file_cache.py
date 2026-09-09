"""Unit tests for cloud_credentials.dump_vault_to_file_cache.

Run via `uv run pytest ansible/tests/ -v`. Exercises against fake
Vault reads and a real tmp filesystem - no real Vault, same reasoning
as test_restore_cloud_credentials_from_backup.py.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cloud_credentials import dump_vault_to_file_cache as dump


class _FakeModule:
    def __init__(self, value: str | None):
        self._value = value

    def read_cache(self, name: str) -> str | None:
        return self._value


class DumpCloudCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def test_writes_present_values_with_owner_only_permissions(self):
        with patch.object(dump, "LEGACY_CACHE_KEYS", [("k", _FakeModule("secret-value"))]):
            written, blank = dump._dump_cloud_credentials(self.tmp)
        self.assertEqual(written, ["k"])
        self.assertEqual(blank, [])
        dest = self.tmp / "k"
        self.assertEqual(dest.read_text(), "secret-value")
        self.assertEqual(dest.stat().st_mode & 0o777, 0o600)

    def test_reports_missing_value_as_blank_not_an_error(self):
        with patch.object(dump, "LEGACY_CACHE_KEYS", [("k", _FakeModule(None))]):
            written, blank = dump._dump_cloud_credentials(self.tmp)
        self.assertEqual(written, [])
        self.assertEqual(blank, ["k"])
        self.assertFalse((self.tmp / "k").exists())


class DumpHostsScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.registry_file = self.tmp / "registry.yaml"

    def _seed_registry(self, text: str) -> None:
        self.registry_file.write_text(text)

    def test_skips_entries_without_a_vault_scope(self):
        self._seed_registry("secrets_registry:\n  no-scope-key:\n    format: manual\n")
        dest = self.tmp / "out"
        dest.mkdir()
        with patch.object(dump, "REGISTRY_PATH", self.registry_file), patch.object(dump, "read_vault_path", return_value="v"):
            written, blank = dump._dump_hosts_scope(dest)
        self.assertEqual(written, [])
        self.assertEqual(blank, [])

    def test_writes_scoped_entry_from_its_declared_path(self):
        self._seed_registry("secrets_registry:\n  telegram-token:\n    format: manual\n    vault_scope: hosts/all/telegram\n")
        dest = self.tmp / "out"
        dest.mkdir()
        calls = []

        def fake_read(path: str) -> str | None:
            calls.append(path)
            return "the-token"

        with patch.object(dump, "REGISTRY_PATH", self.registry_file), patch.object(dump, "read_vault_path", side_effect=fake_read):
            written, _blank = dump._dump_hosts_scope(dest)

        self.assertEqual(written, ["telegram-token"])
        self.assertEqual(calls, ["hosts/all/telegram/telegram-token"])
        self.assertEqual((dest / "telegram-token").read_text(), "the-token")


class OciMisfileCheckTests(unittest.TestCase):
    def test_flags_a_value_present_only_under_the_wrong_category(self):
        def fake_read(path: str) -> str | None:
            return "user-ocid-value" if path.startswith("cloud_credentials/leaf/") else None

        with patch.object(dump, "read_vault_path", side_effect=fake_read):
            report = dump._check_oci_leaf_user_ocid_misfile()

        self.assertIn("rotation/ (expected): MISSING", report)
        self.assertIn("leaf/     (suspect):  present", report)

    def test_never_prints_the_actual_secret_value(self):
        def fake_read(path: str) -> str | None:
            return "super-secret-ocid" if path.startswith("cloud_credentials/leaf/") else None

        with patch.object(dump, "read_vault_path", side_effect=fake_read):
            report = dump._check_oci_leaf_user_ocid_misfile()

        self.assertNotIn("super-secret-ocid", report)


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def test_creates_a_fresh_owner_only_directory_each_run(self):
        registry_file = self.tmp / "registry.yaml"
        registry_file.write_text("secrets_registry:\n  no-scope-key:\n    format: manual\n")
        with (
            patch.object(dump, "REGISTRY_PATH", registry_file),
            patch.object(dump, "LEGACY_CACHE_KEYS", []),
            patch.object(dump, "read_vault_path", return_value=None),
            patch.object(Path, "home", return_value=self.tmp),
        ):
            rc = dump.main()
        self.assertEqual(rc, 0)
        backups = [p for p in self.tmp.iterdir() if p.name.startswith("secrets-backup-pre-reinit-")]
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o700)

    def test_refuses_to_clobber_an_existing_backup_directory(self):
        # _backup_dir() is timestamped, but exist_ok=False is the actual
        # guarantee - assert the real failure mode, not just that two
        # calls happen to get different timestamps.
        with patch.object(dump, "_backup_dir", return_value=self.tmp / "collision"):
            (self.tmp / "collision").mkdir()
            registry_file = self.tmp / "registry.yaml"
            registry_file.write_text("secrets_registry: {}\n")
            with (
                patch.object(dump, "REGISTRY_PATH", registry_file),
                patch.object(dump, "LEGACY_CACHE_KEYS", []),
                self.assertRaises(FileExistsError),
            ):
                dump.main()


if __name__ == "__main__":
    unittest.main()
