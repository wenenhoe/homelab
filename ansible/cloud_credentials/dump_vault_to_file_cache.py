#!/usr/bin/env python3
"""One-time, read-only safety net: pull every current Vault value this
repo knows about into a fresh timestamped backup directory, for use
before a destructive OpenBao re-init (see
docs/openbao-migration-roadmap.md's Open items - root-token recovery).

Opposite direction from migrate_legacy_cache_to_vault.py (file -> Vault,
once); this one goes Vault -> file, and is meant to be re-run before any
operation that could lose Vault's data, not just once ever - rotation
since the last migration means the file cache alone is stale for
several keys (see audit_vault_state.py's DIFFERS report).

Covers:
  - Every cloud_credentials leaf/rotation key (_legacy_cache_keys.py's
    LEGACY_CACHE_KEYS), read via each key's own registered category.
  - Every secrets_registry.yaml entry with a vault_scope (the secrets
    role's hosts/* material, ADR 0024).
  - A live cross-check for _oci-leaf-user-ocid-{read,write}: reads both
    the leaf/ and rotation/ paths, not just the one LEGACY_CACHE_KEYS
    says is correct - a suspected migration mis-file, confirmed here
    rather than assumed.

Does NOT cover main-domain/openbao-controller-role-id/-secret-id -
these never enter Vault at all (cache.py's own docstring), so
ansible/files/secrets/ is already their only copy.

Never overwrites an existing backup: every run gets its own
UTC-timestamped directory under $HOME.

Usage (run from ansible/, needs the same Vault reachability as any
other cloud_credentials script):
    python3 -m cloud_credentials.dump_vault_to_file_cache
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from cloud_credentials._legacy_cache_keys import LEGACY_CACHE_KEYS
from cloud_credentials.cache import PROJECT_ROOT, read_vault_path

REGISTRY_PATH = PROJECT_ROOT / "ansible/inventory/group_vars/all/secrets_registry.yaml"


def _backup_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path.home() / f"secrets-backup-pre-reinit-{stamp}"


def _write(dest: Path, name: str, value: str) -> None:
    path = dest / name
    path.write_text(value)
    path.chmod(0o600)


def _dump_cloud_credentials(dest: Path) -> tuple[list[str], list[str]]:
    written, blank = [], []
    for name, module in LEGACY_CACHE_KEYS:
        value = module.read_cache(name)
        if value is None:
            blank.append(name)
            continue
        _write(dest, name, value)
        written.append(name)
    return written, blank


def _dump_hosts_scope(dest: Path) -> tuple[list[str], list[str]]:
    with REGISTRY_PATH.open() as f:
        registry = yaml.safe_load(f)["secrets_registry"]
    written, blank = [], []
    for name, entry in registry.items():
        scope = entry.get("vault_scope")
        if not scope:
            continue  # cloud_credentials-managed, or a permanent file-cache-only exception - not this function's concern
        value = read_vault_path(f"{scope}/{name}")
        if value is None:
            blank.append(name)
            continue
        _write(dest, name, value)
        written.append(name)
    return written, blank


def _check_oci_leaf_user_ocid_misfile() -> str:
    """_oci-leaf-user-ocid-{read,write} are rotation-scoped in current
    code (oci_bootstrap.py's write_cache, leaf_keys/oci.py's own read -
    both bound to scoped("rotation")) and in _legacy_cache_keys.py's own
    migration table. Suspected: an earlier migration run wrote these
    under cloud_credentials/leaf/ instead. Reads both candidate paths
    directly rather than assuming either is empty."""
    lines = []
    for leaf in ("read", "write"):
        name = f"_oci-leaf-user-ocid-{leaf}"
        at_rotation = read_vault_path(f"cloud_credentials/rotation/{name}")
        at_leaf = read_vault_path(f"cloud_credentials/leaf/{name}")
        lines.append(f"  {name}:")
        lines.append(f"    rotation/ (expected): {'present' if at_rotation is not None else 'MISSING'}")
        lines.append(f"    leaf/     (suspect):  {'present' if at_leaf is not None else 'absent'}")
        if at_rotation is not None and at_leaf is not None:
            lines.append(f"    -> both present, values {'match' if at_rotation == at_leaf else 'DIFFER'}")
    return "\n".join(lines)


def main() -> int:
    dest = _backup_dir()
    dest.mkdir(mode=0o700, parents=True, exist_ok=False)

    cc_written, cc_blank = _dump_cloud_credentials(dest)
    hosts_written, hosts_blank = _dump_hosts_scope(dest)

    print(f"Backed up {len(cc_written) + len(hosts_written)} secrets to {dest}")
    print(f"  cloud_credentials: {len(cc_written)} written, {len(cc_blank)} blank/missing (expected for allow_blank entries)")
    print(f"  hosts/* (secrets role): {len(hosts_written)} written, {len(hosts_blank)} blank/missing")
    if cc_blank:
        print("\ncloud_credentials blank/missing:")
        for name in cc_blank:
            print(f"  {name}")
    if hosts_blank:
        print("\nhosts/* blank/missing:")
        for name in hosts_blank:
            print(f"  {name}")

    print("\n_oci-leaf-user-ocid-{read,write} location check:")
    print(_check_oci_leaf_user_ocid_misfile())

    print(
        "\nNot backed up - these never enter Vault at all, see cache.py's own docstring: main-domain, openbao-controller-role-id, openbao-controller-secret-id."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
