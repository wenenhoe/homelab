"""Cloudflare R2's rotation credential can't be minted via API at all
— confirmed live, see leaf_keys/r2.py:r2_rotation_token's own docstring
— so there's nothing here to create, only to cache. This exists purely
so create_rotation_keys.py can offer the same --provider/--rotate
shape for all three providers, even though R2's version of "rotate" is
just "ask for the Console-created token again and overwrite the
cache" — no verify-then-revoke is possible, unlike B2/OCI. By the time
you've rolled the Custom Token in the Console, the old one is already
revoked; there is nothing left to verify before revoking.
"""

from __future__ import annotations

from cloud_credentials.cache import cached, write_cache
from cloud_credentials.leaf_keys.r2 import _prompt_r2_admin_token

_CACHE_KEY = "_rotation-key-cloudflare-r2-token"


def cache_r2_rotation_token() -> None:
    """Idempotent, matching create_b2_rotation_key/create_oci_rotation_key's
    shape — skips if a token is already cached, so this is safe to run
    unconditionally as part of a routine bootstrap pass."""
    if cached(_CACHE_KEY):
        print("r2: rotation token already cached, skipping")
        return
    write_cache(_CACHE_KEY, _prompt_r2_admin_token())
    print("r2: rotation token cached")


def rotate_r2_rotation_token() -> bool:
    """Overwrites the cached token unconditionally — always returns
    True, since there's no API call here to fail and no old value left
    to verify against. The real-world trigger for this is rolling the
    Custom Token in the Console, which revokes the old one immediately;
    the cached value is already dead by the time this runs regardless
    of what it currently says, so there's no "old key kept working"
    guarantee to offer the way B2/OCI's --rotate does."""
    if cached(_CACHE_KEY):
        print("r2: overwriting cached rotation token — the old value is not verified or revoked here, only replaced")
    write_cache(_CACHE_KEY, _prompt_r2_admin_token())
    print("r2: rotation token cached")
    return True
