"""Shared secrets-cache helpers for cloud_credentials' two scripts.

Both create_leaf_keys.py and create_rotation_keys.py read/write plain
files under SECRETS_DIR as their cache - no database, no encryption at
rest beyond the directory's 0700/0600 permissions (matches
bootstrap_secrets.py's own convention for manually-provisioned secrets).
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SECRETS_DIR = PROJECT_ROOT / "ansible/files/secrets"


def cached(name: str) -> bool:
    return (SECRETS_DIR / name).exists()


def read_cache(name: str) -> str | None:
    """Stripped contents if cached, else None. Collapses the
    `if cached(x): y = ...read_text().strip()` idiom into one call, and
    keeps SECRETS_DIR itself private to this module - every other
    module reads/writes secrets only through these functions, never by
    touching SECRETS_DIR directly, so patching it in tests (or changing
    its layout later) only ever needs to happen in one place."""
    path = SECRETS_DIR / name
    return path.read_text().strip() if path.exists() else None


def cache_path(name: str) -> Path:
    """The Path itself, for the rare caller that needs to hand a path
    to something else (e.g. OCISigner's private_key_file_location)
    rather than read the contents - still without exposing SECRETS_DIR
    directly."""
    return SECRETS_DIR / name


def write_cache(name: str, value: str) -> None:
    dest = SECRETS_DIR / name
    dest.write_text(value)
    dest.chmod(0o600)


def require_cache_file(name: str, how_to_get_it: str) -> str:
    path = SECRETS_DIR / name
    if not path.exists():
        print(f"Missing required cache file: {name}", file=sys.stderr)
        print(f"  {how_to_get_it}", file=sys.stderr)
        sys.exit(1)
    return path.read_text().strip()
