"""Unit tests for diff_vault_backups.

Run via `uv run pytest ansible/tests/ -v`. Real tmp directories with
real files - this tool is pure filesystem comparison, no Vault
involved, so no mocking needed.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cloud_credentials import diff_vault_backups as diff


class DiffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.dir_a = self.tmp / "a"
        self.dir_b = self.tmp / "b"
        self.dir_a.mkdir()
        self.dir_b.mkdir()

    def _write(self, d: Path, name: str, value: str) -> None:
        (d / name).write_text(value)

    def test_identical_directories_return_zero(self):
        self._write(self.dir_a, "key1", "same-value")
        self._write(self.dir_b, "key1", "same-value")
        rc = diff._compare(self.dir_a, self.dir_b, set())
        self.assertEqual(rc, 0)

    def test_differing_value_returns_one(self):
        self._write(self.dir_a, "key1", "old-value")
        self._write(self.dir_b, "key1", "new-value")
        rc = diff._compare(self.dir_a, self.dir_b, set())
        self.assertEqual(rc, 1)

    def test_key_only_in_a_returns_one(self):
        self._write(self.dir_a, "orphan-key", "value")
        self._write(self.dir_a, "shared", "x")
        self._write(self.dir_b, "shared", "x")
        rc = diff._compare(self.dir_a, self.dir_b, set())
        self.assertEqual(rc, 1)

    def test_key_only_in_b_returns_one(self):
        self._write(self.dir_a, "shared", "x")
        self._write(self.dir_b, "shared", "x")
        self._write(self.dir_b, "new-key", "value")
        rc = diff._compare(self.dir_a, self.dir_b, set())
        self.assertEqual(rc, 1)

    def test_ignored_key_does_not_affect_verdict_even_if_it_differs(self):
        self._write(self.dir_a, "rotated-key", "old-value")
        self._write(self.dir_b, "rotated-key", "new-value")
        self._write(self.dir_a, "shared", "x")
        self._write(self.dir_b, "shared", "x")
        rc = diff._compare(self.dir_a, self.dir_b, {"rotated-key"})
        self.assertEqual(rc, 0)

    def test_ignored_key_only_present_in_one_side_does_not_affect_verdict(self):
        self._write(self.dir_a, "dropped-key", "value")
        self._write(self.dir_a, "shared", "x")
        self._write(self.dir_b, "shared", "x")
        rc = diff._compare(self.dir_a, self.dir_b, {"dropped-key"})
        self.assertEqual(rc, 0)

    def test_never_prints_a_secret_value(self):
        self._write(self.dir_a, "key1", "super-secret-value-a")
        self._write(self.dir_b, "key1", "super-secret-value-b")
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            diff._compare(self.dir_a, self.dir_b, set())

        output = buf.getvalue()
        self.assertNotIn("super-secret-value-a", output)
        self.assertNotIn("super-secret-value-b", output)
        self.assertIn("key1", output)

    def test_main_rejects_a_non_directory_argument(self):
        from unittest.mock import patch

        with patch.object(sys, "argv", ["diff_vault_backups.py", str(self.dir_a), str(self.tmp / "nope")]):
            rc = diff.main()
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
