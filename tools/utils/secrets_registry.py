"""The one reader of ansible/inventory/group_vars/all/secrets_registry.yaml.

Standard library and PyYAML only, so a pre-commit hook can import it in an
environment that holds nothing else (`utils/repo.py` pulls in paramiko).
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_RELATIVE = "ansible/inventory/group_vars/all/secrets_registry.yaml"
REGISTRY_PATH = REPO_ROOT / REGISTRY_RELATIVE

Registry = dict[str, dict[str, object]]


class RegistryError(Exception):
    """The registry can't be read, or isn't a mapping of secret name -> mapping."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """safe_load keeps the last of two equal keys, so a repeated secret name would silently replace the first."""

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if isinstance(key, str) and key in seen:
                raise yaml.constructor.ConstructorError(None, None, f"found duplicate key {key!r}", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep)


def _label(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def load_registry(path: Path = REGISTRY_PATH) -> Registry:
    """The `secrets_registry` mapping in `path`: secret name -> its spec."""
    label = _label(path)
    try:
        data = yaml.load(path.read_text(), Loader=_UniqueKeyLoader)  # noqa: S506 - SafeLoader subclass
    except OSError as exc:
        raise RegistryError(f"can't read {label}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise RegistryError(f"{label} isn't valid YAML: {exc}") from exc
    registry = data.get("secrets_registry") if isinstance(data, dict) else None
    if not isinstance(registry, dict) or not all(isinstance(spec, dict) for spec in registry.values()):
        raise RegistryError(f"{label} must hold a `secrets_registry` mapping of name -> mapping")
    return registry


STORES = ("openbao", "controller_file")


def store_of(name: str, spec: dict[str, object]) -> str:
    """Where `name` is kept. A missing or unknown `store` is an error, never a default, so no entry is silently in neither place."""
    store = spec.get("store")
    if store not in STORES:
        raise RegistryError(f"`{name}` must state `store` as one of {', '.join(STORES)}, not {store!r}")
    return store


def file_cache_entries(registry: Registry) -> Registry:
    """The entries kept in the controller-side file cache: those with `store: controller_file`."""
    return {name: spec for name, spec in registry.items() if store_of(name, spec) == "controller_file"}


def openbao_scopes(registry: Registry) -> dict[str, str]:
    """Entry name -> `scope` for every entry with `store: openbao`; its OpenBao path is `<scope>/<name>`."""
    scopes = {}
    for name, spec in registry.items():
        if store_of(name, spec) != "openbao":
            continue
        scope = spec.get("scope")
        if not isinstance(scope, str) or not scope:
            raise RegistryError(f"`{name}` has `store: openbao` but no `scope`")
        scopes[name] = scope
    return scopes
