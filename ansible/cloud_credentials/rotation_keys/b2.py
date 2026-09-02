"""Backblaze B2 rotation-key bootstrap: mint a narrower key, from the
master credential, that can create/delete leaf keys but holds no
file/bucket-data capabilities itself.
"""
from __future__ import annotations

import getpass

import requests

from cloud_credentials.cache import cached, write_cache

B2_AUTHORIZE_URL = "https://api.backblazeb2.com/b2api/v2/b2_authorize_account"


def create_b2_rotation_key() -> None:
    if cached("_rotation-key-backblaze-b2-key-id") and cached(
        "_rotation-key-backblaze-b2-application-key"
    ):
        print("b2: rotation key already cached, skipping")
        return

    print("Backblaze B2 master key ID (B2 Console > Application Keys):")
    master_key_id = getpass.getpass("> ")
    print("Backblaze B2 master application key — input hidden, held in memory only:")
    master_key = getpass.getpass("> ")

    resp = requests.get(B2_AUTHORIZE_URL, auth=(master_key_id, master_key))
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
        },
    )
    key_resp.raise_for_status()
    body = key_resp.json()
    write_cache("_rotation-key-backblaze-b2-key-id", body["applicationKeyId"])
    write_cache("_rotation-key-backblaze-b2-application-key", body["applicationKey"])
    print("b2: rotation key cached")
