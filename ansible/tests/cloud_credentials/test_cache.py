"""Unit tests for cloud_credentials.cache.

Run via `uv run pytest ansible/tests/ -v`. All I/O is against a real
tmp_path directory (patched onto cache.SECRETS_DIR) - no mocking of the
filesystem itself, since this module's entire job is filesystem I/O.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cloud_credentials import cache  # noqa: E402


class CacheTests(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(cache, "SECRETS_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_cached_false_when_missing(self):
        self.assertFalse(cache.cached("does-not-exist"))

    def test_cached_true_after_write(self):
        cache.write_cache("some-key", "value")
        self.assertTrue(cache.cached("some-key"))

    def test_write_cache_sets_owner_only_permissions(self):
        cache.write_cache("secret", "value")
        mode = (self.tmp / "secret").stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_read_cache_returns_none_when_missing(self):
        self.assertIsNone(cache.read_cache("does-not-exist"))

    def test_read_cache_strips_whitespace(self):
        (self.tmp / "with-newline").write_text("value\n")
        self.assertEqual(cache.read_cache("with-newline"), "value")

    def test_cache_path_does_not_require_the_file_to_exist(self):
        # Callers that need a Path to hand to something else (e.g.
        # OCISigner's private_key_file_location) shouldn't be blocked by
        # existence-checking - that's what require_cache_file is for.
        p = cache.cache_path("not-there-yet")
        self.assertEqual(p, self.tmp / "not-there-yet")

    def test_require_cache_file_exits_with_message_when_missing(self):
        with self.assertRaises(SystemExit):
            cache.require_cache_file("missing-key", "run some-command to create it")

    def test_require_cache_file_returns_stripped_contents_when_present(self):
        (self.tmp / "present-key").write_text("  value with spaces  \n")
        self.assertEqual(cache.require_cache_file("present-key", "unused"), "value with spaces")


if __name__ == "__main__":
    unittest.main()
