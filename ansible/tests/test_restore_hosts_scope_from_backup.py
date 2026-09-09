"""Unit tests for restore_hosts_scope_from_backup.

Run via `uv run pytest ansible/tests/ -v`. Fake Vault reads/writes, a
real tmp filesystem for the backup dir and registry file - no real
Vault, same reasoning as test_audit_vault_state.py.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import restore_hosts_scope_from_backup as restore


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.registry_file = self.tmp / "registry.yaml"
        self.backup_dir = self.tmp / "backup"
        self.backup_dir.mkdir()
        patch.object(restore, "REGISTRY_PATH", self.registry_file).start()
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


def _run(backup_dir: Path) -> int:
    with patch.object(sys, "argv", ["restore_hosts_scope_from_backup.py", str(backup_dir)]):
        return restore.main()


if __name__ == "__main__":
    unittest.main()
