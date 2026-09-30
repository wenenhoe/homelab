"""Shared in-memory fake for OpenBao's KV v2 API.

Patches cache._vault_read_at/_vault_write_at - the lowest-level seam,
below both scoped()'s category-based helpers and read_vault_path()'s
direct-path reads - not requests.get/post. Every leaf_keys/
rotation_keys module also calls the bare `requests` module for its own
provider API calls, and patching requests.get/post at cache's level
would collide with a test that separately patches e.g. b2.requests.get
for B2's own HTTP (both names are the exact same shared module
attribute). Patching cache's own two internal functions keeps this
fake scoped to Vault I/O only, regardless of what else a test mocks.

vault_seed()/vault_get()/vault_delete() key by category+name (the
cloud_credentials/{leaf,rotation}/* taxonomy scoped() builds);
vault_seed_path()/vault_get_path() key by a full Vault path directly,
for read_vault_path()'s callers (e.g. check_freshness.py's
hosts/all/telegram/* reads, outside that taxonomy).

FakeVault holds that keying once; FakeVaultTestCase and conftest.py's
fake_vault fixture are the two ways to install it.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from cloud_credentials import cache


class FakeVault:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def write(self, full_path: str, value: str) -> None:
        self.store[full_path] = value

    def seed(self, category: str, name: str, value: str) -> None:
        self.store[cache._vault_path(category, name)] = value

    def get(self, category: str, name: str) -> str | None:
        return self.store.get(cache._vault_path(category, name))

    def delete(self, category: str, name: str) -> None:
        self.store.pop(cache._vault_path(category, name), None)

    def seed_path(self, full_path: str, value: str) -> None:
        self.store[full_path] = value

    def get_path(self, full_path: str) -> str | None:
        return self.store.get(full_path)


class FakeVaultTestCase(unittest.TestCase):
    def setUp(self):
        self._vault = FakeVault()
        self._store = self._vault.store
        patch.object(cache, "_vault_read_at", side_effect=self._store.get).start()
        patch.object(cache, "_vault_write_at", side_effect=self._vault.write).start()
        self.addCleanup(patch.stopall)

    def vault_seed(self, category: str, name: str, value: str) -> None:
        self._vault.seed(category, name, value)

    def vault_get(self, category: str, name: str) -> str | None:
        return self._vault.get(category, name)

    def vault_delete(self, category: str, name: str) -> None:
        self._vault.delete(category, name)

    def vault_seed_path(self, full_path: str, value: str) -> None:
        self._vault.seed_path(full_path, value)

    def vault_get_path(self, full_path: str) -> str | None:
        return self._vault.get_path(full_path)
