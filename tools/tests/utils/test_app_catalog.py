"""Tests for utils.app_catalog: the loader repo tooling reads app_catalog.yaml through.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from utils import app_catalog as ac

CATALOG = {
    "web": {"volumes": [{"name": "data"}], "routes": {"default": {"upstream": "web:80"}}},
    "db": {"volumes": [{"name": "data"}], "backup": {"volumes": ["data"]}},
}

_KEY = ac.CATALOG_KEY


@pytest.fixture
def catalog_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("catalog") / "catalog.yaml"


class TestLoadCatalog:
    def test_returns_the_catalog_mapping(self, catalog_path):
        catalog_path.write_text(yaml.safe_dump({ac.CATALOG_KEY: CATALOG}))
        assert ac.load_catalog(catalog_path) == CATALOG

    def test_a_missing_file_is_an_error_naming_the_path(self, catalog_path):
        with pytest.raises(ac.CatalogError, match=f"can't read {catalog_path}"):
            ac.load_catalog(catalog_path)

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("a: [", id="invalid-yaml"),
            pytest.param("[]", id="top-level-list"),
            pytest.param("other: {}", id="catalog-key-missing"),
            pytest.param(f"{_KEY}: []", id="catalog-is-a-list"),
            pytest.param(f"{_KEY}:\n  x: notamapping\n", id="entry-is-a-string"),
            pytest.param(f"{_KEY}:\n  x:\n", id="entry-is-null"),
            pytest.param(f"{_KEY}:\n  1: {{}}\n", id="app-name-is-not-a-string"),
            pytest.param("", id="empty-file"),
        ],
    )
    def test_invalid_yaml_and_wrong_shapes_are_errors(self, catalog_path, text):
        catalog_path.write_text(text)
        with pytest.raises(ac.CatalogError):
            ac.load_catalog(catalog_path)

    def test_a_repeated_app_name_is_an_error_instead_of_the_last_one_winning(self, catalog_path):
        catalog_path.write_text(f"{ac.CATALOG_KEY}:\n  a: {{ volumes: [] }}\n  a: {{ volumes: [{{ name: x }}] }}\n")
        with pytest.raises(ac.CatalogError, match="duplicate key 'a'"):
            ac.load_catalog(catalog_path)

    def test_a_repeated_key_inside_an_app_is_an_error_too(self, catalog_path):
        catalog_path.write_text(f"{ac.CATALOG_KEY}:\n  a: {{ volumes: [], volumes: [] }}\n")
        with pytest.raises(ac.CatalogError, match="duplicate key 'volumes'"):
            ac.load_catalog(catalog_path)

    def test_a_path_inside_the_repo_is_named_relative_to_it_in_errors(self):
        with pytest.raises(ac.CatalogError, match=r"can't read absent.yaml"):
            ac.load_catalog(ac.REPO_ROOT / "absent.yaml")

    def test_the_real_catalog_loads(self):
        assert ac.load_catalog()


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


@pytest.fixture
def load(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("inventory")

    def _load(**changes: object) -> ac.BackupInventory:
        write_inventory(root, **changes)
        return ac.load_backup_inventory(root)

    return _load


class TestLoadBackupInventory:
    def test_reads_each_fact_the_backup_rules_need(self, load):
        inventory = load()
        assert inventory.defaults == {"cron": "30 4 * * *"}
        assert inventory.cloud_targets == frozenset({"r2", "b2"})
        assert inventory.managed_hosts == ("alpha", "storage")
        assert inventory.compose_apps == {"alpha": [{"name": "web"}], "storage": []}
        assert inventory.host_vars["alpha"]["seaweedfs_s3_access_key"] == "{{ k }}"
        assert inventory.secrets == {"a-secret": {"scope": "hosts/alpha"}}

    def test_values_are_read_not_rendered(self, load):
        assert load().host_vars["alpha"]["seaweedfs_s3_access_key"] == "{{ k }}"

    def test_hosts_keep_the_order_the_inventory_lists_them(self, load):
        hosts = {"zulu": {}, "alpha": {}, "mike": {}}
        inventory = load(**{"inventory.yaml": {"all": {"children": {"managed_hosts": {"hosts": hosts}}}}, "host_vars/zulu.yaml": {}, "host_vars/mike.yaml": {}})
        assert inventory.managed_hosts == ("zulu", "alpha", "mike")

    @pytest.mark.parametrize(
        ("file", "data", "message"),
        [
            pytest.param("group_vars/all/main.yaml", {"other": 1}, "main.yaml must hold a `backup_defaults` mapping", id="main.yaml-no-backup_defaults"),
            pytest.param(
                "group_vars/all/secret_catalog.yaml",
                {"secret_catalog": []},
                "secret_catalog.yaml must hold a `secret_catalog` mapping",
                id="secret_catalog.yaml-not-a-mapping",
            ),
            pytest.param(
                "host_vars/storage.yaml", {"compose_apps": []}, "storage.yaml must hold a `cloud_sync_targets` mapping", id="storage.yaml-no-cloud_sync_targets"
            ),
            pytest.param("inventory.yaml", {"all": {"children": {}}}, "must define the `managed_hosts` group", id="inventory.yaml-no-managed_hosts"),
            pytest.param("host_vars/alpha.yaml", None, "can't read .*alpha.yaml", id="alpha.yaml-missing"),
            pytest.param("group_vars/all/main.yaml", "a: [", "isn't valid YAML", id="main.yaml-invalid-yaml"),
        ],
    )
    def test_a_missing_or_misshapen_file_is_an_error_naming_it(self, load, file, data, message):
        with pytest.raises(ac.CatalogError, match=message):
            load(**{file: data})

    @pytest.mark.parametrize(
        "entries",
        [
            pytest.param("web", id="a-string"),
            pytest.param([{"image": "x"}], id="entry-without-a-name"),
            pytest.param([{"name": 1}], id="name-is-not-a-string"),
            pytest.param(["web"], id="entry-is-a-string"),
        ],
    )
    def test_a_compose_apps_entry_without_a_name_is_an_error(self, load, entries):
        with pytest.raises(ac.CatalogError, match=r"alpha.yaml.*compose_apps"):
            load(**{"host_vars/alpha.yaml": {"compose_apps": entries}})

    def test_a_host_with_no_compose_apps_key_has_none(self, load):
        assert load(**{"host_vars/alpha.yaml": {}}).compose_apps["alpha"] == []

    def test_the_real_inventory_loads(self):
        inventory = ac.load_backup_inventory()
        assert inventory.managed_hosts
        assert inventory.cloud_targets
        assert set(inventory.compose_apps) == set(inventory.managed_hosts)
