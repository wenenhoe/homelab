#!/usr/bin/env python3
"""Audits cloud_sync's R2/B2/OCI secrets for staleness. Two independent
checks, run separately since they need different access:

--local (default, no credentials needed): diffs every file under
ansible/files/secrets/ against secrets_registry.yaml's declared keys plus
the known internal bookkeeping files (_rotation-key-*, _oci-leaf-user-ocid-*)
this repo's own scripts write. Anything else on disk isn't referenced by
current config — a leftover from a naming change, a one-off manual test
file, or similar. Flagged, never deleted by this script.

--provider {oci,b2,r2,all} (needs the same credentials
create_rotation_keys/create_leaf_keys use): lists what
actually exists on each provider's console for the write/read leaves, and
flags anything not matching the currently cached access key as an
apparent orphan — e.g. a key from a rotation that was interrupted or
retried, never cleaned up on the provider's side afterward. Read-only:
lists and flags, never deletes. Delete the flagged ones yourself once
you've confirmed they're not what's live in rclone.conf.

Usage:
    python3 ansible/audit_secrets.py --local
    python3 ansible/audit_secrets.py --provider all --admin-email you@example.com
"""

from __future__ import annotations

import argparse
import fnmatch
import getpass
import sys
from pathlib import Path

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRETS_DIR = PROJECT_ROOT / "ansible/files/secrets"
REGISTRY_PATH = PROJECT_ROOT / "ansible/inventory/group_vars/all/secrets_registry.yaml"

# Cache files this repo's own scripts write outside secrets_registry.yaml
# (that file only covers what the `secrets` Ansible role generates/caches —
# these are create_rotation_keys's own bookkeeping, by design not routed
# through that role). Anything on disk matching neither this nor the
# registry is the actual audit target.
KNOWN_INTERNAL_PATTERNS = [
    "_rotation-key-backblaze-b2-key-id",
    "_rotation-key-backblaze-b2-application-key",
    "_rotation-key-oci-domain-url",
    "_rotation-key-oci-client-id",
    "_rotation-key-oci-client-secret",
    "_rotation-key-oci-app-id",
    "_rotation-key-oci-created-at",
    "_oci-leaf-user-ocid-write",
    "_oci-leaf-user-ocid-read",
    "oci-write-scim-id",
    "oci-read-scim-id",
]

B2_BUCKET = "homelab-backups-b2"


def cached(name: str) -> str | None:
    path = SECRETS_DIR / name
    return path.read_text().strip() if path.exists() else None


# --- Local cache diff ----------------------------------------------------


def audit_local() -> None:
    print("== Local secrets cache vs. secrets_registry.yaml ==")
    registry = yaml.safe_load(REGISTRY_PATH.read_text())["secrets_registry"]
    known = set(registry) | set(KNOWN_INTERNAL_PATTERNS)

    if not SECRETS_DIR.exists():
        print(f"  {SECRETS_DIR} doesn't exist here — nothing to check")
        return

    on_disk = sorted(p.name for p in SECRETS_DIR.iterdir() if p.is_file())
    orphans = [name for name in on_disk if not any(fnmatch.fnmatch(name, pat) for pat in known)]

    if not orphans:
        print(f"  {len(on_disk)} file(s) on disk, all match a current registry/internal entry — nothing to clean up")
        return

    print(f"  {len(orphans)} file(s) not referenced by current config:")
    for name in orphans:
        print(f"    {name}")
    print("\n  Not deleted — confirm these aren't referenced by a branch/host you haven't")
    print("  checked, then: rm " + " ".join(f"ansible/files/secrets/{n}" for n in orphans))


# --- OCI: list customer secret keys per leaf (via SCIM - see ADR 0016) ----


def audit_oci() -> None:
    print("\n== OCI customer secret keys (write + read leaves) ==")
    from cloud_credentials.rotation_keys.oci_scim import oci_scim_session

    try:
        session, domain_url = oci_scim_session()
    except SystemExit:
        # require_cache_file() already printed what's missing and why.
        return

    for leaf in ("write", "read"):
        user_id = cached(f"_oci-leaf-user-ocid-{leaf}")
        active_scim_id = cached(f"oci-{leaf}-scim-id")
        if not user_id:
            print(f"  {leaf}: no cached user OCID, skipping")
            continue
        resp = session.get(f"{domain_url}/admin/v1/CustomerSecretKeys", params={"filter": f'user.ocid eq "{user_id}"'})
        resp.raise_for_status()
        keys = resp.json().get("Resources", [])
        print(f"  {leaf}-leaf user has {len(keys)} customer secret key(s) (OCI allows max 2):")
        for key in keys:
            marker = "ACTIVE (matches cache)" if key["id"] == active_scim_id else "ORPHAN"
            created = key.get("meta", {}).get("created", "unknown")
            print(f"    scim_id={key['id']}  accessKey={key.get('accessKey')}  created={created}  status={key.get('status', 'unknown')}  [{marker}]")
            if marker == "ORPHAN":
                print(f"      delete: DELETE {domain_url}/admin/v1/CustomerSecretKeys/{key['id']}")
                print(f"      or Console: Identity & Security > Users > homelab-cloud-sync-{leaf} > Customer Secret Keys > Delete")


# --- B2: list keys via the rotation key -----------------------------------


def audit_b2() -> None:
    print("\n== B2 application keys (via rotation key) ==")
    rotation_key_id = cached("_rotation-key-backblaze-b2-key-id")
    rotation_key = cached("_rotation-key-backblaze-b2-application-key")
    if not rotation_key_id or not rotation_key:
        print("  no cached rotation key — run python3 -m cloud_credentials.create_rotation_keys --provider b2 first")
        return

    auth = requests.get("https://api.backblazeb2.com/b2api/v2/b2_authorize_account", auth=(rotation_key_id, rotation_key), timeout=45)
    auth.raise_for_status()
    auth = auth.json()
    session = requests.Session()
    session.headers["Authorization"] = auth["authorizationToken"]

    # b2_list_keys is confirmed to exist on v3/v4 in Backblaze's own docs;
    # this repo's create calls all use v2 elsewhere, and v2's list_keys
    # shape isn't independently confirmed here — NEEDS LIVE VERIFICATION,
    # falls back to v4 below if v2 404s.
    for api_version in ("v2", "v4"):
        resp = session.get(
            f"{auth['apiUrl']}/b2api/{api_version}/b2_list_keys",
            params={"accountId": auth["accountId"]},
        )
        if resp.status_code != 404:
            break
    resp.raise_for_status()
    keys = resp.json()["keys"]

    active = {
        cached("backblaze-b2-write-access-key"): "write",
        cached("backblaze-b2-read-access-key"): "read",
        rotation_key_id: "rotation key",
    }
    print(f"  {len(keys)} key(s) on the account (API {api_version}):")
    for key in keys:
        key_id = key["applicationKeyId"]
        marker = f"ACTIVE ({active[key_id]})" if key_id in active else "ORPHAN"
        print(f"    {key_id}  name={key['keyName']}  [{marker}]")
        if marker == "ORPHAN":
            print(f"      delete: b2_delete_key with applicationKeyId={key_id}")
            print("      or Console: App Keys > find this key ID > Delete")


# --- R2: list account-owned tokens -----------------------------------------


def audit_r2() -> None:
    print("\n== Cloudflare R2 account-owned API tokens ==")
    account_id = cached("cloudflare-r2-account-id")
    if not account_id:
        print("  no cached cloudflare-r2-account-id, skipping")
        return
    print("Cloudflare admin token (same one create_leaf_keys asks for — read-only use here, input hidden, held in memory only):")
    token = getpass.getpass("> ")
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    resp = session.get(f"https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens")
    body = resp.json()
    if not body.get("success"):
        print(f"  listing tokens failed: {body.get('errors')}", file=sys.stderr)
        return

    active = {
        cached("cloudflare-r2-write-access-key"): "write",
        cached("cloudflare-r2-read-access-key"): "read",
    }
    tokens = [t for t in body["result"] if t["name"].startswith("homelab-cloud-sync-r2-")]
    print(f"  {len(tokens)} homelab-cloud-sync-r2-* token(s):")
    for t in tokens:
        marker = f"ACTIVE ({active[t['id']]})" if t["id"] in active else "ORPHAN"
        print(f"    {t['id']}  name={t['name']}  status={t['status']}  [{marker}]")
        if marker == "ORPHAN":
            print(f"      delete: DELETE https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens/{t['id']}")
            print("      or Dashboard: Manage Account > Account API Tokens > find this token > Delete")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", help="audit local cache files only (default if no --provider)")
    parser.add_argument("--provider", choices=["oci", "b2", "r2", "all"], help="audit a provider's console side")
    args = parser.parse_args()

    if not args.provider:
        audit_local()
        return 0

    providers = {"oci": audit_oci, "b2": audit_b2, "r2": audit_r2}
    targets = providers if args.provider == "all" else {args.provider: providers[args.provider]}
    for fn in targets.values():
        fn()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
