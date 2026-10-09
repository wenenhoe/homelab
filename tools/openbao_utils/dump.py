#!/usr/bin/env python3
"""Read-only safety net: pull every current Vault value this repo knows
about into a fresh timestamped backup directory, for use before a
destructive OpenBao re-init.

Opposite direction from openbao_utils/restore.py (Vault -> files here,
backup -> Vault there). Re-run it before any operation that could lose
Vault's data; docs/topics/secrets/openbao-reinit-runbook.md is the
consumer of what it produces.

Covers:
  - Every cloud_credentials leaf/rotation secret (secret_owners.py's
    SECRET_OWNERS), read via each name's own registered category.
  - Every secret_catalog.yaml entry with `store: openbao` (the secrets
    role's hosts/* material, ADR 0021).

Does NOT cover main-domain/openbao-controller-role-id/-secret-id -
these never enter Vault at all (cache.py's own docstring), so
ansible/files/secrets/ is already their only copy.

Never overwrites an existing backup: every run gets its own
UTC-timestamped directory under $HOME.

Usage:
    cd tools && python3 -m openbao_utils.dump
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cloud_credentials.cache import read_vault_path
from cloud_credentials.secret_owners import SECRET_OWNERS
from utils.secret_catalog import CATALOG_PATH, load_catalog, openbao_scopes


def _backup_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path.home() / f"secrets-backup-pre-reinit-{stamp}"


def _write(dest: Path, name: str, value: str) -> None:
    path = dest / name
    path.write_text(value)
    path.chmod(0o600)


def _dump_cloud_credentials(dest: Path) -> tuple[list[str], list[str]]:
    written, blank = [], []
    for name, module in SECRET_OWNERS:
        value = module.read_cache(name)
        if value is None:
            blank.append(name)
            continue
        _write(dest, name, value)
        written.append(name)
    return written, blank


def _dump_hosts_scope(dest: Path) -> tuple[list[str], list[str]]:
    catalog = load_catalog(CATALOG_PATH)
    written, blank = [], []
    for name, scope in openbao_scopes(catalog).items():
        value = read_vault_path(f"{scope}/{name}")
        if value is None:
            blank.append(name)
            continue
        _write(dest, name, value)
        written.append(name)
    return written, blank


def main() -> int:
    dest = _backup_dir()
    dest.mkdir(mode=0o700, parents=True, exist_ok=False)

    cc_written, cc_blank = _dump_cloud_credentials(dest)
    hosts_written, hosts_blank = _dump_hosts_scope(dest)

    # A key in both lists (the catalog's cloud_credentials/leaf entries) is the
    # same Vault value and the same file, so it counts once.
    shared = set(cc_written) & set(hosts_written)
    print(f"Backed up {len(set(cc_written) | set(hosts_written))} distinct secrets to {dest}")
    print(f"  cloud_credentials: {len(cc_written)} read, {len(cc_blank)} blank/missing (expected for allow_blank entries)")
    print(f"  hosts/* (secrets role): {len(hosts_written)} read, {len(hosts_blank)} blank/missing")
    if shared:
        print(f"  {len(shared)} keys are listed in both and written once")
    if cc_blank:
        print("\ncloud_credentials blank/missing:")
        for name in cc_blank:
            print(f"  {name}")
    if hosts_blank:
        print("\nhosts/* blank/missing:")
        for name in hosts_blank:
            print(f"  {name}")

    print(
        "\nNot backed up - these never enter Vault at all, see cache.py's own docstring: main-domain, openbao-controller-role-id, openbao-controller-secret-id."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
