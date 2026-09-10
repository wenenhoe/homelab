#!/usr/bin/env python3
"""One-time: restore every cloud_credentials leaf/rotation value from a
cloud_credentials.dump_vault_to_file_cache backup directory into a
freshly re-initialized, otherwise-empty OpenBao.

Replaces migrate_legacy_cache_to_vault.py, retired at Track A stage 6
alongside the file cache it read from (ansible/files/secrets/). That
script's actual remaining job - re-init recovery, per ADR 0025's step 6,
not its original stage-5 migration - needed a real source directory once
the file cache stopped existing; this is that source-directory version,
the restore-side mirror of restore_hosts_scope_from_backup.py for the
cloud_credentials half of the same problem.

Necessary because restore_hosts_scope_from_backup.py only restores
secrets_registry.yaml entries (every vault_scope-carrying key, including
the 20 cloud_credentials/leaf ones a registry entry exists for as of
Track A stage 6). It has no way to reach LEGACY_CACHE_KEYS' remaining
~10 names - _rotation-key-*, _oci-leaf-user-ocid-*, the two scim-ids -
which are cloud_credentials' own internal bookkeeping and were never
registry entries. This script covers the whole LEGACY_CACHE_KEYS list
regardless of registry overlap, since idempotent skip-if-present-in-
Vault makes running both against the same backup harmless either order.

Pure copy, no regeneration, no prompting - same shape as
migrate_legacy_cache_to_vault.py's own now-removed logic, just reading
from the given backup directory instead of the retired ansible/files/
secrets/. Idempotent - skips any key already present in Vault, so it's
safe to re-run if interrupted partway through.

Usage (run from ansible/, after controller's AppRole is recreated per
docs/openbao-auth.md's runbook, BEFORE any deploy.yaml run):
    python3 restore_cloud_credentials_from_backup.py ~/secrets-backup-pre-reinit-<timestamp>/
"""

from __future__ import annotations

import sys
from pathlib import Path

from cloud_credentials._legacy_cache_keys import LEGACY_CACHE_KEYS


def _read_backup_file(backup_dir: Path, name: str) -> str | None:
    path = backup_dir / name
    return path.read_text().strip() if path.exists() else None


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

    for name, module in LEGACY_CACHE_KEYS:
        backup_value = _read_backup_file(backup_dir, name)
        if backup_value is None:
            no_backup_file.append(name)
            continue
        if module.cached(name):
            already_in_vault.append(name)
            continue
        module.write_cache(name, backup_value)
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
