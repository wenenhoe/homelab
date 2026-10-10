"""Fixtures for the cloud_credentials tests."""

from __future__ import annotations

import pytest
from _fake_vault import FakeVault
from cloud_credentials import secret_store


class CategoryVault:
    """seed()/get()/delete() against a FakeVault, defaulting to one category.

    The "leaf" default is what leaf_keys/ and create_snapshot_*'s own outputs use; pass category="rotation"
    for the rotation-tier session credentials those modules read but don't own (B2's rotation key, OCI's leaf
    IAM user OCID, R2's admin token).
    """

    def __init__(self, vault: FakeVault, category: str) -> None:
        self._vault = vault
        self._category = category

    def seed(self, name: str, value: str, category: str | None = None) -> None:
        self._vault.seed(category or self._category, name, value)

    def get(self, name: str, category: str | None = None) -> str | None:
        return self._vault.get(category or self._category, name)

    def delete(self, name: str, category: str | None = None) -> None:
        self._vault.delete(category or self._category, name)


@pytest.fixture
def fake_vault(monkeypatch: pytest.MonkeyPatch) -> FakeVault:
    vault = FakeVault()
    monkeypatch.setattr(secret_store, "_vault_read_at", vault.store.get)
    monkeypatch.setattr(secret_store, "_vault_write_at", vault.write)
    return vault


@pytest.fixture
def vault(fake_vault: FakeVault) -> CategoryVault:
    return CategoryVault(fake_vault, "leaf")


@pytest.fixture
def rotation_vault(fake_vault: FakeVault) -> CategoryVault:
    return CategoryVault(fake_vault, "rotation")
