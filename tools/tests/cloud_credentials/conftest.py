"""Fixtures for the cloud_credentials tests."""

from __future__ import annotations

import pytest
from _fake_vault import FakeVault
from cloud_credentials import cache


@pytest.fixture
def fake_vault(monkeypatch: pytest.MonkeyPatch) -> FakeVault:
    vault = FakeVault()
    monkeypatch.setattr(cache, "_vault_read_at", vault.store.get)
    monkeypatch.setattr(cache, "_vault_write_at", vault.write)
    return vault
