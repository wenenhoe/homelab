"""Unit tests for cloud_credentials.audit_vault_state.

Run via `uv run pytest ansible/tests/ -v`. Exercises _status()'s
classification and main()'s reporting against a fake module double,
not a real Vault - see test_migrate_legacy_cache_to_vault.py's own
comment for why.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cloud_credentials import audit_vault_state as audit


class _FakeModule:
    def __init__(self, value: str | None = None):
        self._value = value

    def read_cache(self, name: str) -> str | None:
        return self._value


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patch.object(audit, "SECRETS_DIR", self.tmp).start()
        self.addCleanup(patch.stopall)

    def seed_file(self, name: str, value: str) -> None:
        (self.tmp / name).write_text(value)

    def test_neither_present_reports_neither(self):
        self.assertEqual(audit._status("k", _FakeModule(None)), "NEITHER")

    def test_file_only_reports_not_yet_migrated(self):
        self.seed_file("k", "v")
        self.assertEqual(audit._status("k", _FakeModule(None)), "FILE ONLY (not yet migrated)")

    def test_vault_only_reports_vault_only(self):
        status = audit._status("k", _FakeModule("v"))
        self.assertTrue(status.startswith("VAULT ONLY"))

    def test_matching_values_report_match(self):
        self.seed_file("k", "same-value")
        self.assertEqual(audit._status("k", _FakeModule("same-value")), "MATCH")

    def test_differing_values_report_differs(self):
        self.seed_file("k", "file-value")
        status = audit._status("k", _FakeModule("vault-value"))
        self.assertTrue(status.startswith("DIFFERS"))

    def test_never_reads_the_secret_value_into_a_status_string(self):
        # The actual safety property this script exists to uphold: no
        # branch of _status() may leak either value into its return
        # string, since main() prints that string straight to stdout.
        self.seed_file("k", "super-secret-file-value")
        status = audit._status("k", _FakeModule("super-secret-vault-value"))
        self.assertNotIn("super-secret-file-value", status)
        self.assertNotIn("super-secret-vault-value", status)


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patch.object(audit, "SECRETS_DIR", self.tmp).start()
        self.addCleanup(patch.stopall)

    def test_returns_zero_even_when_a_differs_entry_is_present(self):
        # This is a report, not a gate - a DIFFERS entry needs a human
        # decision (see this script's own final printed note), not a
        # failed exit code that might get treated as a CI gate.
        (self.tmp / "k").write_text("file-value")
        with patch.object(audit, "LEGACY_CACHE_KEYS", [("k", _FakeModule("vault-value"))]):
            rc = audit.main()
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
