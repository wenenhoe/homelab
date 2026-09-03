"""Backblaze B2 rotation-key bootstrap and rotation: mint a narrower
key, from the master credential, that can create/delete leaf keys but
holds no file/bucket-data capabilities itself.
"""

from __future__ import annotations

import getpass
import sys

import requests

from cloud_credentials.cache import cached, read_cache, write_cache
from cloud_credentials.expiry import QUARTERLY_SECONDS

B2_AUTHORIZE_URL = "https://api.backblazeb2.com/b2api/v2/b2_authorize_account"


def _prompt_master_credentials() -> tuple[str, str]:
    print("Backblaze B2 master key ID (B2 Console > Application Keys):")
    master_key_id = getpass.getpass("> ")
    print("Backblaze B2 master application key — input hidden, held in memory only:")
    master_key = getpass.getpass("> ")
    return master_key_id, master_key


def _mint_rotation_key(master_key_id: str, master_key: str) -> dict:
    resp = requests.get(B2_AUTHORIZE_URL, auth=(master_key_id, master_key), timeout=45)
    resp.raise_for_status()
    auth = resp.json()
    account_id, api_url = auth["accountId"], auth["apiUrl"]
    session = requests.Session()
    session.headers["Authorization"] = auth["authorizationToken"]

    # listKeys/writeKeys/deleteKeys are B2's native "manage other keys"
    # capabilities, independent of writeFiles/readFiles — this key can
    # create and delete application keys but can't read or write file
    # contents itself.
    #
    # No bucketId here — confirmed, not a guess: Backblaze's own docs
    # enumerate every capability a bucket-restricted key is allowed to
    # carry, and listKeys/writeKeys/deleteKeys aren't on that list. Key
    # management is inherently account-wide on B2; a live 400 ("Invalid
    # capability for bucket-level application key") is what surfaced
    # this. This rotation key can create/delete any key on the account,
    # not just ones for homelab-backups-b2 — the actual scoping this key
    # gets is that it holds no file/bucket-data capabilities at all, not
    # that it's bucket-restricted.
    key_resp = session.post(
        f"{api_url}/b2api/v2/b2_create_key",
        json={
            "accountId": account_id,
            "capabilities": ["listKeys", "writeKeys", "deleteKeys", "listBuckets"],
            "keyName": "homelab-cloud-sync-rotation-key",
            "validDurationInSeconds": QUARTERLY_SECONDS,
        },
    )
    key_resp.raise_for_status()
    body = key_resp.json()
    return {"master_session": session, "api_url": api_url, "key_id": body["applicationKeyId"], "app_key": body["applicationKey"]}


def _verify_rotation_key(key_id: str, app_key: str) -> tuple[bool, str]:
    """Authorize with the NEW key standalone (not the master session
    that minted it) and confirm it can list keys — the exact capability
    create_leaf_keys.py depends on, not just "did authorize succeed"."""
    try:
        resp = requests.get(B2_AUTHORIZE_URL, auth=(key_id, app_key), timeout=45)
        resp.raise_for_status()
        auth = resp.json()
        session = requests.Session()
        session.headers["Authorization"] = auth["authorizationToken"]
        session.post(f"{auth['apiUrl']}/b2api/v2/b2_list_keys", json={"accountId": auth["accountId"]}).raise_for_status()
        return True, ""
    except requests.HTTPError as exc:
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
            minted["master_session"].post(f"{minted['api_url']}/b2api/v2/b2_delete_key", json={"applicationKeyId": old_key_id}).raise_for_status()
            print(f"b2: old rotation key {old_key_id} revoked")
        except requests.HTTPError as exc:
            print(
                f"b2: new rotation key verified and will be cached, but revoking old key {old_key_id} failed ({exc}) — revoke it by hand in the B2 Console.",
                file=sys.stderr,
            )

    write_cache("_rotation-key-backblaze-b2-key-id", new_key_id)
    write_cache("_rotation-key-backblaze-b2-application-key", new_app_key)
    print("b2: rotation key rotated and verified")
    return True
