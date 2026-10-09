"""Tests for the fake_vault fixture in conftest.py: that it stands in for Vault I/O at the layer cache.py reads and writes through."""

from __future__ import annotations

import pytest
from cloud_credentials import cache


def test_an_unseeded_read_returns_none_without_opening_a_vault_session(fake_vault):
    assert cache.read_vault_path("cloud_credentials/leaf/never-seeded") is None


@pytest.mark.parametrize("category", ["leaf", "rotation"])
def test_a_seeded_value_is_read_back_through_the_category_scoped_cache(fake_vault, category):
    fake_vault.seed(category, "some-key", "sentinel-7f3a")
    _, read_secret, _, _ = cache.scoped(category)

    assert read_secret("some-key") == "sentinel-7f3a"


@pytest.mark.parametrize("category", ["leaf", "rotation"])
def test_a_write_through_the_scoped_cache_lands_under_the_categorys_vault_path(fake_vault, category):
    _, _, write_secret, _ = cache.scoped(category)

    write_secret("some-key", "written-value")

    assert fake_vault.store == {f"cloud_credentials/{category}/some-key": "written-value"}
    assert fake_vault.get(category, "some-key") == "written-value"


def test_a_path_outside_the_taxonomy_round_trips_by_its_full_path(fake_vault):
    fake_vault.seed_path("hosts/all/telegram/bot-token", "path-sentinel")

    assert cache.read_vault_path("hosts/all/telegram/bot-token") == "path-sentinel"

    cache.write_vault_path("hosts/all/telegram/chat-id", "second-sentinel")

    assert fake_vault.get_path("hosts/all/telegram/chat-id") == "second-sentinel"


def test_delete_removes_only_the_named_entry(fake_vault):
    fake_vault.seed("leaf", "keep", "kept")
    fake_vault.seed("leaf", "drop", "dropped")

    fake_vault.delete("leaf", "drop")

    assert fake_vault.store == {"cloud_credentials/leaf/keep": "kept"}
