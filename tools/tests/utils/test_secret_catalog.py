"""Tests for utils.secret_catalog: the one loader every reader of secret_catalog.yaml goes through.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils import secret_catalog as sr

CATALOG = {
    "main-domain": {"source": "manual", "store": "controller_file"},
    "session-key": {"source": "hex", "length": 32, "store": "openbao", "scope": "hosts/all/x"},
}


class LoadCatalogTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "catalog.yaml"

    def write(self, text: str) -> None:
        self.path.write_text(text)

    def test_returns_the_catalog_mapping(self):
        self.write(yaml.safe_dump({"secret_catalog": CATALOG}))
        self.assertEqual(sr.load_catalog(self.path), CATALOG)

    def test_a_missing_file_is_an_error_naming_the_path(self):
        with self.assertRaisesRegex(sr.CatalogError, f"can't read {self.path}"):
            sr.load_catalog(self.path)

    def test_invalid_yaml_and_wrong_shapes_are_errors(self):
        for text in ("a: [", "[]", "other: {}", "secret_catalog: []", "secret_catalog:\n  x: notamapping\n", ""):
            self.write(text)
            with self.subTest(text=text), self.assertRaises(sr.CatalogError):
                sr.load_catalog(self.path)

    def test_a_repeated_secret_name_is_an_error_instead_of_the_last_one_winning(self):
        self.write("secret_catalog:\n  a: { source: manual }\n  a: { source: hex, length: 8 }\n")
        with self.assertRaisesRegex(sr.CatalogError, "duplicate key 'a'"):
            sr.load_catalog(self.path)

    def test_a_repeated_field_inside_an_entry_is_an_error_too(self):
        self.write("secret_catalog:\n  a: { source: manual, source: hex }\n")
        with self.assertRaisesRegex(sr.CatalogError, "duplicate key 'source'"):
            sr.load_catalog(self.path)

    def test_a_path_inside_the_repo_is_named_relative_to_it_in_errors(self):
        with self.assertRaisesRegex(sr.CatalogError, "can't read absent.yaml"):
            sr.load_catalog(sr.REPO_ROOT / "absent.yaml")


class RealCatalogTests(unittest.TestCase):
    def test_the_default_path_is_the_real_catalog_and_it_loads(self):
        self.assertTrue(sr.CATALOG_PATH.is_file())
        self.assertEqual(sr.CATALOG_PATH, sr.REPO_ROOT / sr.CATALOG_RELATIVE)
        catalog = sr.load_catalog()
        self.assertIn("main-domain", catalog)
        self.assertGreater(len(catalog), 50)


class StoreOfTests(unittest.TestCase):
    def test_returns_the_stated_store(self):
        self.assertEqual(sr.store_of("a", {"store": "openbao"}), "openbao")
        self.assertEqual(sr.store_of("a", {"store": "controller_file"}), "controller_file")

    def test_a_missing_or_unknown_store_is_an_error_naming_the_entry_never_a_default(self):
        for spec in ({}, {"store": None}, {"store": "vault"}, {"store": ""}, {"vault_scope": "hosts/play"}):
            with self.subTest(spec=spec), self.assertRaisesRegex(sr.CatalogError, "`a` must state `store`"):
                sr.store_of("a", spec)


class FileCacheEntriesTests(unittest.TestCase):
    def test_keeps_the_entries_with_store_controller_file(self):
        self.assertEqual(sr.file_cache_entries(CATALOG), {"main-domain": {"source": "manual", "store": "controller_file"}})

    def test_an_empty_catalog_has_none(self):
        self.assertEqual(sr.file_cache_entries({}), {})

    def test_an_entry_with_no_store_is_an_error_instead_of_being_left_out(self):
        with self.assertRaises(sr.CatalogError):
            sr.file_cache_entries({"a": {"source": "manual"}})

    def test_the_real_catalog_keeps_three_in_the_file_cache(self):
        self.assertEqual(
            set(sr.file_cache_entries(sr.load_catalog())),
            {"main-domain", "openbao-controller-role-id", "openbao-controller-secret-id"},
        )


class OpenbaoScopesTests(unittest.TestCase):
    def test_maps_each_openbao_entry_to_its_scope(self):
        self.assertEqual(sr.openbao_scopes(CATALOG), {"session-key": "hosts/all/x"})

    def test_file_cache_entries_have_no_scope_to_report(self):
        self.assertEqual(sr.openbao_scopes({"a": {"store": "controller_file"}}), {})

    def test_an_openbao_entry_without_a_scope_is_an_error(self):
        for spec in ({"store": "openbao"}, {"store": "openbao", "scope": ""}, {"store": "openbao", "scope": None}, {"store": "openbao", "scope": 7}):
            with self.subTest(spec=spec), self.assertRaisesRegex(sr.CatalogError, "`a` has `store: openbao` but no `scope`"):
                sr.openbao_scopes({"a": spec})

    def test_an_entry_with_no_store_is_an_error_instead_of_being_left_out(self):
        with self.assertRaises(sr.CatalogError):
            sr.openbao_scopes({"a": {"scope": "hosts/play"}})

    def test_the_real_catalog_has_57_openbao_entries_and_each_path_is_scope_slash_name(self):
        catalog = sr.load_catalog()
        scopes = sr.openbao_scopes(catalog)
        self.assertEqual(len(scopes), 57)
        self.assertEqual(set(scopes) | set(sr.file_cache_entries(catalog)), set(catalog))
        self.assertEqual(len({f"{scope}/{name}" for name, scope in scopes.items()}), 57)


if __name__ == "__main__":
    unittest.main()
