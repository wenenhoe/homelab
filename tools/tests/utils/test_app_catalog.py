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
    "web": {"volumes": [{"name": "data"}], "routes": {"default": {"upstream": "web:80"}}},
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


def write_inventory(root: Path, **changes: object) -> None:
    """A minimal valid inventory under `root`; `changes` replaces a file's mapping, or removes the file when None."""
    files = {
        "group_vars/all/main.yaml": {"backup_defaults": {"cron": "30 4 * * *"}, "other": "{{ rendered }}"},
        "group_vars/all/secret_catalog.yaml": {"secret_catalog": {"a-secret": {"scope": "hosts/alpha"}, "not-a-mapping": "x"}},
        "host_vars/storage.yaml": {"cloud_sync_targets": {"r2": {"bucket": "b"}, "b2": {}}},
        "inventory.yaml": {"all": {"children": {"managed_hosts": {"hosts": {"alpha": {"ansible_host": "a.{{ d }}"}, "storage": {}}}}}},
        "host_vars/alpha.yaml": {"compose_apps": [{"name": "web"}], "seaweedfs_s3_access_key": "{{ k }}"},
    }
    files.update(changes)
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False))


class LoadBackupInventoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def load(self, **changes: object) -> ac.BackupInventory:
        write_inventory(self.root, **changes)
        return ac.load_backup_inventory(self.root)

    def test_reads_each_fact_the_backup_rules_need(self):
        inventory = self.load()
        self.assertEqual(inventory.defaults, {"cron": "30 4 * * *"})
        self.assertEqual(inventory.cloud_targets, frozenset({"r2", "b2"}))
        self.assertEqual(inventory.managed_hosts, ("alpha", "storage"))
        self.assertEqual(inventory.compose_apps, {"alpha": [{"name": "web"}], "storage": []})
        self.assertEqual(inventory.host_vars["alpha"]["seaweedfs_s3_access_key"], "{{ k }}")
        self.assertEqual(inventory.secrets, {"a-secret": {"scope": "hosts/alpha"}})

    def test_values_are_read_not_rendered(self):
        self.assertEqual(self.load().host_vars["alpha"]["seaweedfs_s3_access_key"], "{{ k }}")

    def test_hosts_keep_the_order_the_inventory_lists_them(self):
        hosts = {"zulu": {}, "alpha": {}, "mike": {}}
        inventory = self.load(
            **{"inventory.yaml": {"all": {"children": {"managed_hosts": {"hosts": hosts}}}}, "host_vars/zulu.yaml": {}, "host_vars/mike.yaml": {}}
        )
        self.assertEqual(inventory.managed_hosts, ("zulu", "alpha", "mike"))

    def test_a_missing_or_misshapen_file_is_an_error_naming_it(self):
        cases = {
            "group_vars/all/main.yaml": ({"other": 1}, "main.yaml must hold a `backup_defaults` mapping"),
            "group_vars/all/secret_catalog.yaml": ({"secret_catalog": []}, "secret_catalog.yaml must hold a `secret_catalog` mapping"),
            "host_vars/storage.yaml": ({"compose_apps": []}, "storage.yaml must hold a `cloud_sync_targets` mapping"),
            "inventory.yaml": ({"all": {"children": {}}}, "must define the `managed_hosts` group"),
            "host_vars/alpha.yaml": (None, "can't read .*alpha.yaml"),
            "group_vars/all/main.yaml ": ("a: [", "isn't valid YAML"),
        }
        for changes, (data, message) in cases.items():
            with self.subTest(file=changes), self.assertRaisesRegex(ac.CatalogError, message):
                write_inventory(self.root)
                self.load(**{changes.strip(): data})

    def test_a_compose_apps_entry_without_a_name_is_an_error(self):
        for entries in ("web", [{"image": "x"}], [{"name": 1}], ["web"]):
            with self.subTest(entries=entries), self.assertRaisesRegex(ac.CatalogError, "alpha.yaml.*compose_apps"):
                self.load(**{"host_vars/alpha.yaml": {"compose_apps": entries}})

    def test_a_host_with_no_compose_apps_key_has_none(self):
        self.assertEqual(self.load(**{"host_vars/alpha.yaml": {}}).compose_apps["alpha"], [])

    def test_the_real_inventory_loads(self):
        inventory = ac.load_backup_inventory()
        self.assertTrue(inventory.managed_hosts)
        self.assertTrue(inventory.cloud_targets)
        self.assertEqual(set(inventory.compose_apps), set(inventory.managed_hosts))


if __name__ == "__main__":
    unittest.main()
