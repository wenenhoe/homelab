"""Backblaze B2 rotation-key bootstrap and rotation: mint a narrower
key, from the master credential, that can create/delete leaf keys but
holds no file/bucket-data capabilities itself. Via b2sdk (Stage 3,
docs/projects/cloud-credentials-hardening.md).
"""

from __future__ import annotations

import getpass
import sys

from b2sdk.v2 import B2Api, InMemoryAccountInfo
from b2sdk.v2.exception import B2Error

from cloud_credentials.cache import scoped
from cloud_credentials.expiry import QUARTERLY_SECONDS

cached, read_cache, write_cache, _ = scoped("rotation")


def _prompt_master_credentials() -> tuple[str, str]:
    print("Backblaze B2 master key ID (B2 Console > Application Keys):")
    master_key_id = getpass.getpass("> ")
    print("Backblaze B2 master application key — input hidden, held in memory only:")
    master_key = getpass.getpass("> ")
    return master_key_id, master_key


def _mint_rotation_key(master_key_id: str, master_key: str) -> dict:
    master_api = B2Api(InMemoryAccountInfo())
    master_api.authorize_account("production", master_key_id, master_key)

    # listKeys/writeKeys/deleteKeys are B2's native "manage other keys"
    # capabilities, independent of writeFiles/readFiles — this key can
    # create and delete application keys but can't read or write file
    # contents itself.
    #
    # No bucket_id here — confirmed, not a guess: Backblaze's own docs
    # enumerate every capability a bucket-restricted key is allowed to
    # carry, and listKeys/writeKeys/deleteKeys aren't on that list. Key
    # management is inherently account-wide on B2; a live 400 ("Invalid
    # capability for bucket-level application key") is what surfaced
    # this. This rotation key can create/delete any key on the account,
    # not just ones for homelab-backups-b2 — the actual scoping this key
    # gets is that it holds no file/bucket-data capabilities at all, not
    # that it's bucket-restricted.
    key = master_api.create_key(
        capabilities=["listKeys", "writeKeys", "deleteKeys", "listBuckets"],
        key_name="homelab-cloud-sync-rotation-key",
        valid_duration_seconds=QUARTERLY_SECONDS,
    )
    return {"master_api": master_api, "key_id": key.id_, "app_key": key.application_key}


def _verify_rotation_key(key_id: str, app_key: str) -> tuple[bool, str]:
    """Authorize with the NEW key standalone (not the master session
    that minted it) and confirm it can list keys — the exact capability
    create_leaf_keys.py depends on, not just "did authorize succeed"."""
    try:
        api = B2Api(InMemoryAccountInfo())
        api.authorize_account("production", key_id, app_key)
        list(api.list_keys())
        return True, ""
    except B2Error as exc:
        return False, str(exc)


def create_b2_rotation_key() -> None:
    if cached("_rotation-key-backblaze-b2-key-id") and cached("_rotation-key-backblaze-b2-application-key"):
        print("b2: rotation key already cached, skipping")
        return

    master_key_id, master_key = _prompt_master_credentials()
    minted = _mint_rotation_key(master_key_id, master_key)
    write_cache("_rotation-key-backblaze-b2-key-id", minted["key_id"])
    write_cache("_rotation-key-backblaze-b2-application-key", minted["app_key"])
    print("b2: rotation key cached")


def rotate_b2_rotation_key() -> bool:
    """Mint a new rotation key from the master credential, verify it can
    actually list keys, only then revoke the old one — same
    verify-before-revoke shape as leaf key rotation
    (leaf_keys/b2.py:rotate_b2), applied one level up. Requires the
    master credential every time, same as create_b2_rotation_key —
    B2 has no way to mint an account-management key from another
    account-management key, only from the master."""
    old_key_id = read_cache("_rotation-key-backblaze-b2-key-id")

    master_key_id, master_key = _prompt_master_credentials()
    minted = _mint_rotation_key(master_key_id, master_key)
    new_key_id, new_app_key = minted["key_id"], minted["app_key"]

    ok, detail = _verify_rotation_key(new_key_id, new_app_key)
    if not ok:
        print(
            f"b2: new rotation key {new_key_id} failed verification ({detail}). "
            f"Old rotation key {old_key_id or '(none cached)'} left untouched and still in use; "
            f"new key left live but NOT cached or revoked — investigate, then either "
            f"retry or revoke {new_key_id} by hand in the B2 Console.",
            file=sys.stderr,
        )
        return False

    if old_key_id:
        try:
            minted["master_api"].session.delete_key(old_key_id)
            print(f"b2: old rotation key {old_key_id} revoked")
        except B2Error as exc:
            print(
                f"b2: new rotation key verified and will be cached, but revoking old key {old_key_id} failed ({exc}) — revoke it by hand in the B2 Console.",
                file=sys.stderr,
            )

    write_cache("_rotation-key-backblaze-b2-key-id", new_key_id)
    write_cache("_rotation-key-backblaze-b2-application-key", new_app_key)
    print("b2: rotation key rotated and verified")
    return True
