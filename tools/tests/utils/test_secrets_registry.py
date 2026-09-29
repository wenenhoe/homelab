"""Tests for utils.secrets_registry: the one loader every reader of secrets_registry.yaml goes through.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils import secrets_registry as sr

REGISTRY = {
    "main-domain": {"format": "manual"},
    "session-key": {"format": "hex", "length": 32, "vault_scope": "hosts/all/x"},
}


class LoadRegistryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "registry.yaml"

    def write(self, text: str) -> None:
        self.path.write_text(text)

    def test_returns_the_registry_mapping(self):
        self.write(yaml.safe_dump({"secrets_registry": REGISTRY}))
        self.assertEqual(sr.load_registry(self.path), REGISTRY)

    def test_a_missing_file_is_an_error_naming_the_path(self):
        with self.assertRaisesRegex(sr.RegistryError, f"can't read {self.path}"):
            sr.load_registry(self.path)

    def test_invalid_yaml_and_wrong_shapes_are_errors(self):
        for text in ("a: [", "[]", "other: {}", "secrets_registry: []", "secrets_registry:\n  x: notamapping\n", ""):
            self.write(text)
            with self.subTest(text=text), self.assertRaises(sr.RegistryError):
                sr.load_registry(self.path)

    def test_a_repeated_secret_name_is_an_error_instead_of_the_last_one_winning(self):
        self.write("secrets_registry:\n  a: { format: manual }\n  a: { format: hex, length: 8 }\n")
        with self.assertRaisesRegex(sr.RegistryError, "duplicate key 'a'"):
            sr.load_registry(self.path)

    def test_a_repeated_field_inside_an_entry_is_an_error_too(self):
        self.write("secrets_registry:\n  a: { format: manual, format: hex }\n")
        with self.assertRaisesRegex(sr.RegistryError, "duplicate key 'format'"):
            sr.load_registry(self.path)

    def test_a_path_inside_the_repo_is_named_relative_to_it_in_errors(self):
        with self.assertRaisesRegex(sr.RegistryError, "can't read absent.yaml"):
            sr.load_registry(sr.REPO_ROOT / "absent.yaml")


class RealRegistryTests(unittest.TestCase):
    def test_the_default_path_is_the_real_registry_and_it_loads(self):
        self.assertTrue(sr.REGISTRY_PATH.is_file())
        self.assertEqual(sr.REGISTRY_PATH, sr.REPO_ROOT / sr.REGISTRY_RELATIVE)
        registry = sr.load_registry()
        self.assertIn("main-domain", registry)
        self.assertGreater(len(registry), 50)


class FileCacheEntriesTests(unittest.TestCase):
    def test_keeps_the_entries_with_no_vault_scope(self):
        self.assertEqual(sr.file_cache_entries(REGISTRY), {"main-domain": {"format": "manual"}})

    def test_an_empty_registry_has_none(self):
        self.assertEqual(sr.file_cache_entries({}), {})

    def test_the_real_registry_keeps_three_in_the_file_cache(self):
        self.assertEqual(
            set(sr.file_cache_entries(sr.load_registry())),
            {"main-domain", "openbao-controller-role-id", "openbao-controller-secret-id"},
        )


if __name__ == "__main__":
    unittest.main()
