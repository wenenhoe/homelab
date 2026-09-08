#!/usr/bin/env python3
"""One-time migration: copy every cloud_credentials value already
cached in ansible/files/secrets/ into its correct OpenBao KV v2 path
(Track A stage 5, ADR 0018/0019).

Necessary because stage 5's storage repoint changed where the code
looks, not what already exists: a controller with real credentials
cached before this stage landed would otherwise have those credentials
become invisible to check_freshness.py/create_leaf_keys.py/
create_rotation_keys.py, even though every one of them is still valid
and working provider-side.

A pure copy, nothing else: no re-minting, no provider API calls, no
prompting. Idempotent - skips any key already present in Vault, the
same cached()-then-write() guard every create_*/rotate_* function in
this package already uses, so it's safe to re-run. Never deletes the
legacy file cache; that's Track A stage 6's job, only after a full
cutover drill proves Vault is the sole working source (see
docs/openbao-migration-roadmap.md).

Usage (run from ansible/, after docs/openbao-auth.md's stage 3 runbook):
    python3 -m cloud_credentials.migrate_legacy_cache_to_vault
"""

from __future__ import annotations

from cloud_credentials._legacy_cache_keys import LEGACY_CACHE_KEYS
from cloud_credentials.cache import SECRETS_DIR


def _read_legacy_file(name: str) -> str | None:
    path = SECRETS_DIR / name
    return path.read_text().strip() if path.exists() else None


def main() -> int:
    migrated: list[str] = []
    already_in_vault: list[str] = []
    no_legacy_file: list[str] = []

    for name, module in LEGACY_CACHE_KEYS:
        legacy_value = _read_legacy_file(name)
        if legacy_value is None:
            no_legacy_file.append(name)
            continue
        if module.cached(name):
            already_in_vault.append(name)
            continue
        module.write_cache(name, legacy_value)
        migrated.append(name)

    print(f"Migrated to Vault ({len(migrated)}):")
    for name in migrated:
        print(f"  {name}")
    if already_in_vault:
        print(f"\nAlready in Vault, left untouched ({len(already_in_vault)}):")
        for name in already_in_vault:
            print(f"  {name}")
    if no_legacy_file:
        print(f"\nNo legacy cache file found, nothing to migrate ({len(no_legacy_file)}):")
        for name in no_legacy_file:
            print(f"  {name}")

    print(
        "\nLegacy files under ansible/files/secrets/ were not touched or "
        "deleted - that happens at Track A stage 6's cutover, only after "
        "a full restore drill proves Vault is the sole working source."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
