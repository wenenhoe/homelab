"""The reader of ansible/inventory/group_vars/all/app_registry.yaml for repo tooling.

Standard library and PyYAML only, so a pre-commit hook can import it. Ansible
reads the same file through the `resolve_apps` filter, not through this module.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from utils.unique_key_yaml import UniqueKeyLoader

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_RELATIVE = "ansible/inventory/group_vars/all/app_registry.yaml"
CATALOG_PATH = REPO_ROOT / CATALOG_RELATIVE
CATALOG_KEY = "app_registry"

Catalog = dict[str, dict[str, object]]


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
