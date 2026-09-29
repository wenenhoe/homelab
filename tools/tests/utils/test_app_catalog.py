"""Tests for utils.app_catalog: the loader repo tooling reads app_catalog.yaml through.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils import app_catalog as ac

CATALOG = {
    "web": {"volumes": [{"name": "data"}], "caddy": {"default": {"upstream": "web:80"}}},
    "db": {"volumes": [{"name": "data"}], "backup": {"volumes": ["data"]}},
}


class LoadCatalogTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "catalog.yaml"

    def write(self, text: str) -> None:
        self.path.write_text(text)

    def test_returns_the_catalog_mapping(self):
        self.write(yaml.safe_dump({ac.CATALOG_KEY: CATALOG}))
        self.assertEqual(ac.load_catalog(self.path), CATALOG)

    def test_a_missing_file_is_an_error_naming_the_path(self):
        with self.assertRaisesRegex(ac.CatalogError, f"can't read {self.path}"):
            ac.load_catalog(self.path)

    def test_invalid_yaml_and_wrong_shapes_are_errors(self):
        key = ac.CATALOG_KEY
        for text in ("a: [", "[]", "other: {}", f"{key}: []", f"{key}:\n  x: notamapping\n", f"{key}:\n  x:\n", f"{key}:\n  1: {{}}\n", ""):
            self.write(text)
            with self.subTest(text=text), self.assertRaises(ac.CatalogError):
                ac.load_catalog(self.path)

    def test_a_repeated_app_name_is_an_error_instead_of_the_last_one_winning(self):
        self.write(f"{ac.CATALOG_KEY}:\n  a: {{ volumes: [] }}\n  a: {{ volumes: [{{ name: x }}] }}\n")
        with self.assertRaisesRegex(ac.CatalogError, "duplicate key 'a'"):
            ac.load_catalog(self.path)

    def test_a_repeated_key_inside_an_app_is_an_error_too(self):
        self.write(f"{ac.CATALOG_KEY}:\n  a: {{ volumes: [], volumes: [] }}\n")
        with self.assertRaisesRegex(ac.CatalogError, "duplicate key 'volumes'"):
            ac.load_catalog(self.path)

    def test_a_path_inside_the_repo_is_named_relative_to_it_in_errors(self):
        with self.assertRaisesRegex(ac.CatalogError, "can't read absent.yaml"):
            ac.load_catalog(ac.REPO_ROOT / "absent.yaml")

    def test_the_real_catalog_loads(self):
        self.assertTrue(ac.load_catalog())


if __name__ == "__main__":
    unittest.main()
