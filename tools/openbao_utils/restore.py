#!/usr/bin/env python3
"""One-time: restore every secret/data/hosts/*-scoped value and every
cloud_credentials leaf/rotation value from a
openbao_utils.dump backup directory into a
freshly re-initialized, otherwise-empty OpenBao.

Necessary before the first `ansible-playbook deploy.yaml` against a
freshly re-initialized Vault: `ensure_secret.yaml`'s generate-once-if-
missing logic would otherwise see nothing at these paths and mint new
random values for all of this catalog's hex/uuid4 entries - silently
invalidating already-deployed services that still expect the old value
(lldap's live JWT secret, SeaweedFS access keys cloud_sync/backup_agent
currently authenticate with, etc.). This restores the exact prior
value instead of letting anything regenerate.

Two phases:
  1. Every secret_catalog.yaml entry with `store: openbao` (every
     `hosts/*` secret, plus the cloud_credentials/leaf ones a catalog
     entry exists for) - via cache.py's
     read_vault_path()/write_vault_path() escape hatch.
  2. cloud_credentials' own internal bookkeeping names, which have no
     secret_catalog.yaml entry of their own (_rotation-key-*,
     _oci-leaf-user-ocid-*, the two oci-{write,read}-scim-id values)
     and which phase 1 has no way to reach - via each name's owning
     module in SECRET_OWNERS.

Pure copy, no regeneration, no prompting. Idempotent - skips any value
already present in Vault, so it's safe to re-run if interrupted
partway through. Every backup file is restored byte-for-byte, never
stripped: openbao_utils/dump.py writes the raw Vault value with
no added whitespace, so stripping on the way back in would silently
rewrite any value that legitimately has meaningful leading/trailing
whitespace.

Usage:
    cd tools && python3 -m openbao_utils.restore ~/secrets-backup-pre-reinit-<timestamp>/
"""

from __future__ import annotations

import sys
from pathlib import Path

from cloud_credentials.cache import read_vault_path, write_vault_path
from cloud_credentials.secret_owners import SECRET_OWNERS
from utils.secret_catalog import CATALOG_PATH, load_catalog, openbao_scopes


def _scoped_catalog_entries() -> dict[str, str]:
    return openbao_scopes(load_catalog(CATALOG_PATH))


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

    for name, scope in _scoped_catalog_entries().items():
        backup_file = backup_dir / name
        if not backup_file.exists():
            no_backup_file.append(name)
            continue
        if read_vault_path(f"{scope}/{name}") is not None:
            already_in_vault.append(name)
            continue
        write_vault_path(f"{scope}/{name}", backup_file.read_text())
        restored.append(name)

    for name, module in SECRET_OWNERS:
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
