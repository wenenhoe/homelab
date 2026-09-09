#!/usr/bin/env python3
"""One-time: restore every secret/data/hosts/*-scoped value from a
cloud_credentials.dump_vault_to_file_cache backup directory into a
freshly re-initialized, otherwise-empty OpenBao.

Necessary before the first `ansible-playbook deploy.yaml` against a
freshly re-initialized Vault: `ensure_secret.yaml`'s generate-once-if-
missing logic would otherwise see nothing at these paths and mint new
random values for all of this registry's hex/uuid4 entries - silently
invalidating already-deployed services that still expect the old value
(lldap's live JWT secret, SeaweedFS access keys cloud_sync/backup_agent
currently authenticate with, etc.). This restores the exact prior
value instead of letting anything regenerate.

Pure copy, no regeneration, no prompting - the restore-side mirror of
dump_vault_to_file_cache.py's own backup pass, and of
migrate_legacy_cache_to_vault.py's shape for the cloud_credentials
half of this same problem. Idempotent - skips any key already present
in Vault, so it's safe to re-run if interrupted partway through.

Usage (run from ansible/, after controller's AppRole is recreated per
docs/openbao-auth.md's runbook, BEFORE any deploy.yaml run):
    python3 restore_hosts_scope_from_backup.py ~/secrets-backup-pre-reinit-<timestamp>/
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from cloud_credentials.cache import PROJECT_ROOT, read_vault_path, write_vault_path

REGISTRY_PATH = PROJECT_ROOT / "ansible/inventory/group_vars/all/secrets_registry.yaml"


def _scoped_registry_entries() -> dict[str, str]:
    with REGISTRY_PATH.open() as f:
        registry = yaml.safe_load(f)["secrets_registry"]
    return {name: spec["vault_scope"] for name, spec in registry.items() if spec.get("vault_scope")}


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <backup-directory>", file=sys.stderr)
        return 1

    backup_dir = Path(sys.argv[1]).expanduser()
    if not backup_dir.is_dir():
        print(f"Not a directory: {backup_dir}", file=sys.stderr)
        return 1

    restored, already_in_vault, no_backup_file = [], [], []

    for name, scope in _scoped_registry_entries().items():
        backup_file = backup_dir / name
        if not backup_file.exists():
            no_backup_file.append(name)
            continue
        if read_vault_path(f"{scope}/{name}") is not None:
            already_in_vault.append(name)
            continue
        write_vault_path(f"{scope}/{name}", backup_file.read_text())
        restored.append(name)

    print(f"Restored to Vault ({len(restored)}):")
    for name in restored:
        print(f"  {name}")
    if already_in_vault:
        print(f"\nAlready in Vault, left untouched ({len(already_in_vault)}):")
        for name in already_in_vault:
            print(f"  {name}")
    if no_backup_file:
        print(f"\nNo backup file found, nothing to restore ({len(no_backup_file)}):")
        for name in no_backup_file:
            print(f"  {name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
