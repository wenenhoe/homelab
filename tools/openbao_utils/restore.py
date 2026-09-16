#!/usr/bin/env python3
"""One-time: restore every secret/data/hosts/*-scoped value and every
cloud_credentials leaf/rotation value from a
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

Two phases, covering two Vault-path shapes that don't overlap:
  1. Every secrets_registry.yaml entry with a vault_scope (every
     `hosts/*` key, plus the 20 cloud_credentials/leaf ones a registry
     entry exists for as of Track A stage 6) - via cache.py's
     read_vault_path()/write_vault_path() escape hatch.
  2. cloud_credentials' own internal bookkeeping keys with no
     secrets_registry.yaml entry of their own (_rotation-key-*,
     _oci-leaf-user-ocid-*, the two oci-{write,read}-scim-id values) -
     the ~10 LEGACY_CACHE_KEYS names phase 1 has no way to reach,
     via each key's own registered module.

Replaces migrate_legacy_cache_to_vault.py (retired at Track A stage 6
alongside the file cache it read from, ansible/files/secrets/) and the
two separate scripts this file merges -
restore_hosts_scope_from_backup.py and
restore_cloud_credentials_from_backup.py - always run as one logical
operation against the same backup directory (openbao-reinit-runbook.md's
old steps 5/6, now one step).

Pure copy, no regeneration, no prompting. Idempotent - skips any key
already present in Vault, so it's safe to re-run if interrupted
partway through. Every backup file is restored byte-for-byte, never
stripped: dump_vault_to_file_cache.py writes the raw Vault value with
no added whitespace, so stripping on the way back in would silently
rewrite any value that legitimately has meaningful leading/trailing
whitespace - a real discrepancy between the two scripts this one
replaces, resolved in favor of the non-stripping, byte-for-byte
behavior on merge.

Usage:
    cd tools && python3 -m openbao_utils.restore ~/secrets-backup-pre-reinit-<timestamp>/
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from cloud_credentials._legacy_cache_keys import LEGACY_CACHE_KEYS
from cloud_credentials.cache import read_vault_path, write_vault_path
from utils.repo import PROJECT_ROOT

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

    restored: list[str] = []
    already_in_vault: list[str] = []
    no_backup_file: list[str] = []

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

    for name, module in LEGACY_CACHE_KEYS:
        backup_file = backup_dir / name
        if not backup_file.exists():
            no_backup_file.append(name)
            continue
        if module.cached(name):
            already_in_vault.append(name)
            continue
        module.write_cache(name, backup_file.read_text())
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
