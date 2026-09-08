"""Shared base for leaf_keys/test_{r2,b2,oci}.py's rotation tests.

Uses the fake in-memory Vault (ansible/tests/cloud_credentials/
_fake_vault.py) instead of a real file cache - every provider module
reads/writes secrets only through cache.scoped()'s bound functions,
never a raw HTTP call of their own, so faking cache's own session/HTTP
layer in one place is sufficient everywhere.

seed()/get() default to the "leaf" category, since that's what these
modules' own create/rotate outputs use - pass category="rotation" for
the rotation-tier session credentials (B2's rotation key, OCI's leaf
IAM user OCID, R2's admin token) these modules read but don't own.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _fake_vault import FakeVaultTestCase


class RotationTestBase(FakeVaultTestCase):
    def seed(self, name: str, value: str, category: str = "leaf") -> None:
        self.vault_seed(category, name, value)

    def get(self, name: str, category: str = "leaf") -> str | None:
        return self.vault_get(category, name)
