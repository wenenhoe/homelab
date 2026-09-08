#!/usr/bin/env python3
"""Read-only audit: for every cloud_credentials leaf/rotation key,
report whether it's in Vault, in the legacy file cache, both, or
neither - without ever printing an actual secret value.

Exists to answer one question safely before running
migrate_legacy_cache_to_vault.py: has anything already landed at these
Vault paths (e.g. from an earlier, now-lost migration attempt), and if
so, does it match what's still in the file cache or has it diverged?

Deliberately a probe against a known, finite list of paths, not a
recursive Vault listing - controller's Era A policy (controller.hcl)
grants create/read/update on specific path prefixes only, no `list`
capability anywhere, so a true "show me everything under
cloud_credentials/*" isn't possible without a policy change. That's a
deliberate scope decision to flag, not work around here: widening
controller's policy is a real, separate change this script doesn't
make for you.

Usage (run from ansible/):
    python3 -m cloud_credentials.audit_vault_state
"""

from __future__ import annotations

from cloud_credentials._legacy_cache_keys import LEGACY_CACHE_KEYS
from cloud_credentials.cache import SECRETS_DIR


def _read_legacy_file(name: str) -> str | None:
    path = SECRETS_DIR / name
    return path.read_text().strip() if path.exists() else None


def _status(name: str, module) -> str:
    file_value = _read_legacy_file(name)
    vault_value = module.read_cache(name)

    if vault_value is None and file_value is None:
        return "NEITHER"
    if vault_value is None:
        return "FILE ONLY (not yet migrated)"
    if file_value is None:
        return "VAULT ONLY (no legacy file - already migrated, or never file-cached)"
    return "MATCH" if vault_value == file_value else "DIFFERS (Vault and file cache disagree)"


def main() -> int:
    by_status: dict[str, list[str]] = {}
    for name, module in LEGACY_CACHE_KEYS:
        status = _status(name, module)
        by_status.setdefault(status, []).append(name)

    status_order = (
        "MATCH",
        "FILE ONLY (not yet migrated)",
        "VAULT ONLY (no legacy file - already migrated, or never file-cached)",
        "DIFFERS (Vault and file cache disagree)",
        "NEITHER",
    )
    for status in status_order:
        names = by_status.get(status, [])
        if not names:
            continue
        print(f"{status} ({len(names)}):")
        for name in names:
            print(f"  {name}")
        print()

    if by_status.get("DIFFERS (Vault and file cache disagree)"):
        print(
            "A DIFFERS entry most often just means this credential was "
            "rotated after the file-to-Vault migration ran: every rotate "
            "since then writes the new value to Vault only, so the legacy "
            "file is now stale by design - expected, not a conflict, if "
            "you rotated it on purpose. It's only worth investigating "
            "further if you did NOT expect this specific credential to "
            "have changed."
        )

    print(
        "This only checked the specific paths cloud_credentials uses. "
        "controller's policy grants no `list` capability, so this can't "
        "detect a value written somewhere unexpected - see this script's "
        "own module docstring."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
