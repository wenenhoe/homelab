"""Reading ansible/inventory/group_vars/all/secrets_registry.yaml for the CI fixtures."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_RELATIVE = "ansible/inventory/group_vars/all/secrets_registry.yaml"


class RegistryError(Exception):
    """The registry isn't shaped the way the fixtures need."""


def load_registry(root: Path) -> dict[str, dict[str, object]]:
    """The `secrets_registry` mapping: secret name -> its spec."""
    path = root / REGISTRY_RELATIVE
    try:
        data = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise RegistryError(f"can't read {REGISTRY_RELATIVE}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise RegistryError(f"{REGISTRY_RELATIVE} isn't valid YAML: {exc}") from exc
    registry = data.get("secrets_registry") if isinstance(data, dict) else None
    if not isinstance(registry, dict) or not all(isinstance(spec, dict) for spec in registry.values()):
        raise RegistryError(f"{REGISTRY_RELATIVE} must hold a `secrets_registry` mapping of name -> mapping")
    return registry
