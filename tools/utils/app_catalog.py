"""The reader of ansible/inventory/group_vars/all/app_catalog.yaml for repo tooling.

Standard library and PyYAML only, so a pre-commit hook can import it. Ansible
reads the same file through the `resolve_apps` filter, not through this module.
`load_backup_inventory` also reads, as plain YAML and without rendering a single
value, the other inventory files a backup check needs (ADR 0068).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from utils.unique_key_yaml import UniqueKeyLoader

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_RELATIVE = "ansible/inventory/group_vars/all/app_catalog.yaml"
CATALOG_PATH = REPO_ROOT / CATALOG_RELATIVE
CATALOG_KEY = "app_catalog"
INVENTORY_DIR = REPO_ROOT / "ansible/inventory"

Catalog = dict[str, dict[str, object]]


@dataclass(frozen=True)
class BackupInventory:
    """What the backup rules check the catalog against, read from the inventory's plain YAML."""

    defaults: dict[str, object]  # group_vars/all/main.yaml: backup_defaults
    cloud_targets: frozenset[str]  # host_vars/storage.yaml: the keys of cloud_sync_targets
    managed_hosts: tuple[str, ...]  # inventory.yaml: the hosts of the managed_hosts group, in order
    compose_apps: dict[str, list[dict[str, object]]]  # each managed host's own compose_apps entries
    host_vars: dict[str, dict[str, object]]  # each managed host's host_vars mapping
    secrets: dict[str, dict[str, object]]  # group_vars/all/secret_catalog.yaml: secret_catalog


class CatalogError(Exception):
    """The catalog can't be read, or isn't a mapping of app name -> mapping."""


def _label(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def load_catalog(path: Path = CATALOG_PATH) -> Catalog:
    """The catalog mapping in `path`: app name -> its definition. A repeated app name is an error."""
    label = _label(path)
    try:
        data = yaml.load(path.read_text(), Loader=UniqueKeyLoader)  # noqa: S506 - SafeLoader subclass
    except OSError as exc:
        raise CatalogError(f"can't read {label}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise CatalogError(f"{label} isn't valid YAML: {exc}") from exc
    catalog = data.get(CATALOG_KEY) if isinstance(data, dict) else None
    if not isinstance(catalog, dict) or not all(isinstance(name, str) and isinstance(app, dict) for name, app in catalog.items()):
        raise CatalogError(f"{label} must hold a `{CATALOG_KEY}` mapping of name -> mapping")
    return catalog


def _load_mapping(path: Path) -> dict[str, object]:
    label = _label(path)
    try:
        data = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise CatalogError(f"can't read {label}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise CatalogError(f"{label} isn't valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise CatalogError(f"{label} must be a mapping")
    return data


def _mapping_at(data: dict[str, object], key: str, path: Path) -> dict[str, object]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise CatalogError(f"{_label(path)} must hold a `{key}` mapping")
    return value


def load_backup_inventory(root: Path = INVENTORY_DIR) -> BackupInventory:
    """The inventory facts the backup rules need. Anything missing or misshapen is a CatalogError."""
    main_path = root / "group_vars/all/main.yaml"
    defaults = _mapping_at(_load_mapping(main_path), "backup_defaults", main_path)

    storage_path = root / "host_vars/storage.yaml"
    targets = _mapping_at(_load_mapping(storage_path), "cloud_sync_targets", storage_path)

    secrets_path = root / "group_vars/all/secret_catalog.yaml"
    secrets = _mapping_at(_load_mapping(secrets_path), "secret_catalog", secrets_path)

    inventory_path = root / "inventory.yaml"
    group = _load_mapping(inventory_path).get("all")
    hosts = group.get("children", {}).get("managed_hosts", {}).get("hosts") if isinstance(group, dict) else None
    if not isinstance(hosts, dict) or not all(isinstance(host, str) for host in hosts):
        raise CatalogError(f"{_label(inventory_path)} must define the `managed_hosts` group with its hosts")

    compose_apps: dict[str, list[dict[str, object]]] = {}
    host_vars: dict[str, dict[str, object]] = {}
    for host in hosts:
        host_path = root / f"host_vars/{host}.yaml"
        host_vars[host] = _load_mapping(host_path)
        entries = host_vars[host].get("compose_apps", [])
        if not isinstance(entries, list) or not all(isinstance(e, dict) and isinstance(e.get("name"), str) for e in entries):
            raise CatalogError(f"{_label(host_path)}: `compose_apps` must be a list of mappings that each have a `name`")
        compose_apps[host] = entries

    return BackupInventory(
        defaults=defaults,
        cloud_targets=frozenset(targets),
        managed_hosts=tuple(hosts),
        compose_apps=compose_apps,
        host_vars=host_vars,
        secrets={name: entry for name, entry in secrets.items() if isinstance(entry, dict)},
    )
