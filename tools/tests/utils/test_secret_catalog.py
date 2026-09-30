"""Tests for utils.secret_catalog: the one loader every reader of secret_catalog.yaml goes through.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from utils import secret_catalog as sr

CATALOG = {
    "main-domain": {"source": "manual", "store": "controller_file"},
    "session-key": {"source": "hex", "length": 32, "store": "openbao", "scope": "hosts/all/x"},
}


@pytest.fixture
def catalog_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("catalog") / "catalog.yaml"


class TestLoadCatalog:
    def test_returns_the_catalog_mapping(self, catalog_path):
        catalog_path.write_text(yaml.safe_dump({"secret_catalog": CATALOG}))
        assert sr.load_catalog(catalog_path) == CATALOG

    def test_a_missing_file_is_an_error_naming_the_path(self, catalog_path):
        with pytest.raises(sr.CatalogError, match=f"can't read {catalog_path}"):
            sr.load_catalog(catalog_path)

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("a: [", id="invalid-yaml"),
            pytest.param("[]", id="top-level-list"),
            pytest.param("other: {}", id="catalog-key-missing"),
            pytest.param("secret_catalog: []", id="catalog-is-a-list"),
            pytest.param("secret_catalog:\n  x: notamapping\n", id="entry-is-a-string"),
            pytest.param("", id="empty-file"),
        ],
    )
    def test_invalid_yaml_and_wrong_shapes_are_errors(self, catalog_path, text):
        catalog_path.write_text(text)
        with pytest.raises(sr.CatalogError):
            sr.load_catalog(catalog_path)

    def test_a_repeated_secret_name_is_an_error_instead_of_the_last_one_winning(self, catalog_path):
        catalog_path.write_text("secret_catalog:\n  a: { source: manual }\n  a: { source: hex, length: 8 }\n")
        with pytest.raises(sr.CatalogError, match="duplicate key 'a'"):
            sr.load_catalog(catalog_path)

    def test_a_repeated_field_inside_an_entry_is_an_error_too(self, catalog_path):
        catalog_path.write_text("secret_catalog:\n  a: { source: manual, source: hex }\n")
        with pytest.raises(sr.CatalogError, match="duplicate key 'source'"):
            sr.load_catalog(catalog_path)

    def test_a_path_inside_the_repo_is_named_relative_to_it_in_errors(self):
        with pytest.raises(sr.CatalogError, match=r"can't read absent.yaml"):
            sr.load_catalog(sr.REPO_ROOT / "absent.yaml")


class TestRealCatalog:
    def test_the_default_path_is_the_real_catalog_and_it_loads(self):
        assert sr.CATALOG_PATH.is_file()
        assert sr.CATALOG_PATH == sr.REPO_ROOT / sr.CATALOG_RELATIVE
        catalog = sr.load_catalog()
        assert "main-domain" in catalog
        assert len(catalog) > 50


class TestStoreOf:
    def test_returns_the_stated_store(self):
        assert sr.store_of("a", {"store": "openbao"}) == "openbao"
        assert sr.store_of("a", {"store": "controller_file"}) == "controller_file"

    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param({}, id="empty-spec"),
            pytest.param({"store": None}, id="store-is-null"),
            pytest.param({"store": "vault"}, id="unknown-store"),
            pytest.param({"store": ""}, id="store-is-empty"),
            pytest.param({"vault_scope": "hosts/play"}, id="no-store-key"),
        ],
    )
    def test_a_missing_or_unknown_store_is_an_error_naming_the_entry_never_a_default(self, spec):
        with pytest.raises(sr.CatalogError, match="`a` must state `store`"):
            sr.store_of("a", spec)


class TestFileCacheEntries:
    def test_keeps_the_entries_with_store_controller_file(self):
        assert sr.file_cache_entries(CATALOG) == {"main-domain": {"source": "manual", "store": "controller_file"}}

    def test_an_empty_catalog_has_none(self):
        assert sr.file_cache_entries({}) == {}

    def test_an_entry_with_no_store_is_an_error_instead_of_being_left_out(self):
        with pytest.raises(sr.CatalogError):
            sr.file_cache_entries({"a": {"source": "manual"}})

    def test_the_real_catalog_keeps_three_in_the_file_cache(self):
        assert set(sr.file_cache_entries(sr.load_catalog())) == {"main-domain", "openbao-controller-role-id", "openbao-controller-secret-id"}


class TestOpenbaoScopes:
    def test_maps_each_openbao_entry_to_its_scope(self):
        assert sr.openbao_scopes(CATALOG) == {"session-key": "hosts/all/x"}

    def test_file_cache_entries_have_no_scope_to_report(self):
        assert sr.openbao_scopes({"a": {"store": "controller_file"}}) == {}

    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param({"store": "openbao"}, id="no-scope-key"),
            pytest.param({"store": "openbao", "scope": ""}, id="scope-is-empty"),
            pytest.param({"store": "openbao", "scope": None}, id="scope-is-null"),
            pytest.param({"store": "openbao", "scope": 7}, id="scope-is-not-a-string"),
        ],
    )
    def test_an_openbao_entry_without_a_scope_is_an_error(self, spec):
        with pytest.raises(sr.CatalogError, match="`a` has `store: openbao` but no `scope`"):
            sr.openbao_scopes({"a": spec})

    def test_an_entry_with_no_store_is_an_error_instead_of_being_left_out(self):
        with pytest.raises(sr.CatalogError):
            sr.openbao_scopes({"a": {"scope": "hosts/play"}})

    def test_the_real_catalog_has_57_openbao_entries_and_each_path_is_scope_slash_name(self):
        catalog = sr.load_catalog()
        scopes = sr.openbao_scopes(catalog)
        assert len(scopes) == 57
        assert set(scopes) | set(sr.file_cache_entries(catalog)) == set(catalog)
        assert len({f"{scope}/{name}" for name, scope in scopes.items()}) == 57
