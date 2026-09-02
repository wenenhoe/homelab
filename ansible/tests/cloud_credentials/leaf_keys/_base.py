"""Shared base for leaf_keys/test_{r2,b2,oci}.py's rotation tests.

Patches cache.SECRETS_DIR (not any individual provider module's own
name) to a tmp dir - correct as of the cache.py refactor that made
SECRETS_DIR fully private to cache.py: every provider module reads/
writes secrets only through cached()/write_cache()/read_cache()/
require_cache_file(), never by importing SECRETS_DIR directly, so
patching it in exactly one place is sufficient everywhere.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cloud_credentials import cache


class RotationTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(cache, "SECRETS_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def seed(self, name: str, value: str) -> None:
        cache.write_cache(name, value)
