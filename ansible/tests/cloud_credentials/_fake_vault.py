"""Shared in-memory fake for OpenBao's KV v2 API.

Patches cache._vault_read/_vault_write directly, not requests.get/post -
every leaf_keys/rotation_keys module also calls the bare `requests`
module for its own provider API calls, and patching requests.get/post
at cache's level would collide with a test that separately patches
e.g. b2.requests.get for B2's own HTTP (both names are the exact same
shared module attribute). Patching cache's own two internal functions
keeps this fake scoped to Vault I/O only, regardless of what else a
test mocks.

Keyed by the exact path cache._vault_path builds, so tests seed/assert
through the same category/name pair the code under test actually uses.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from cloud_credentials import cache


class FakeVaultTestCase(unittest.TestCase):
    def setUp(self):
        self._store: dict[str, str] = {}
        patch.object(cache, "_vault_read", side_effect=self._vault_read).start()
        patch.object(cache, "_vault_write", side_effect=self._vault_write).start()
        self.addCleanup(patch.stopall)

    def _vault_read(self, category: str, name: str) -> str | None:
        return self._store.get(cache._vault_path(category, name))

    def _vault_write(self, category: str, name: str, value: str) -> None:
        self._store[cache._vault_path(category, name)] = value

    def vault_seed(self, category: str, name: str, value: str) -> None:
        self._store[cache._vault_path(category, name)] = value

    def vault_get(self, category: str, name: str) -> str | None:
        return self._store.get(cache._vault_path(category, name))

    def vault_delete(self, category: str, name: str) -> None:
        self._store.pop(cache._vault_path(category, name), None)
