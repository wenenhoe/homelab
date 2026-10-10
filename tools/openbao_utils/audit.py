#!/usr/bin/env python3
"""Audits cloud_sync's R2/B2/OCI secrets for staleness. Two independent
checks, run separately since they need different access:

--local (default, no credentials needed): diffs every file under
ansible/files/secrets/ against secret_catalog.yaml's declared keys.
Two different findings, not one:
  - A file whose catalog entry has `store: openbao` is stale — Vault is
    that entry's only real source; the file predates that move and nothing has read it since. Flagged
    separately from a genuine orphan because it isn't unreferenced by
    name, just unreferenced by mechanism — confirm Vault actually has
    the value (this check alone doesn't, deliberately: that needs a
    live Vault session, and this mode's whole point is not needing
    one) before deleting.
  - A name matching neither a catalog entry nor cloud_credentials'
    own internal bookkeeping (SECRET_OWNERS) is a genuine orphan —
    a stray manual test file, a leftover from a naming change, or
    similar.
Neither category is deleted by this script.

--provider {oci,b2,r2,all} (needs the same credentials
create_rotation_keys/create_leaf_keys use): reads currently-active
values from OpenBao (the same Vault store those scripts write
to - secret_store.py's scoped()), lists what actually exists on each
provider's console for the write/read leaves, and flags anything not
matching the access key currently in Vault as an apparent orphan — e.g. a
key from a rotation that was interrupted or retried, never cleaned up
on the provider's side afterward. Read-only: lists and flags, never
deletes. Delete the flagged ones yourself once you've confirmed they're
not what's live in rclone.conf.

Usage:
    cd tools && python3 -m openbao_utils.audit --local
    cd tools && python3 -m openbao_utils.audit --provider all --admin-email you@example.com
"""

from __future__ import annotations

import argparse
import getpass
import sys

import requests
from cloud_credentials.leaf_keys.b2 import b2_list_keys, b2_rotation_api
from cloud_credentials.rotation_keys.oci_scim import oci_identity_domains_client
from cloud_credentials.secret_owners import SECRET_OWNERS
from utils.repo import SECRETS_DIR
from utils.secret_catalog import CATALOG_PATH, load_catalog, openbao_scopes

B2_BUCKET = "homelab-backups-b2"

_OWNER_BY_NAME = dict(SECRET_OWNERS)


def read_secret(name: str) -> str | None:
    """Reads via cloud_credentials' own Vault-backed store (secret_store.py's
    scoped()) - the real store for every SECRET_OWNERS name, never
    the controller-side file cache. name must be one of SECRET_OWNERS' own names -
    a KeyError here means this script asked for a name that package
    doesn't own, not a runtime possibility to paper over."""
    return _OWNER_BY_NAME[name].read_secret(name)


# --- Controller file cache diff -------------------------------------------


def audit_local() -> None:
    print("== Controller file cache vs. secret_catalog.yaml ==")
    catalog = load_catalog(CATALOG_PATH)
    vault_backed_scope = openbao_scopes(catalog)
    # cloud_credentials' own internal bookkeeping names (_rotation-key-*,
    # _oci-leaf-user-ocid-*, the two scim-ids) have no secret_catalog.yaml
    # entry of their own, so SECRET_OWNERS' name list is what makes them
    # known here.
    known = set(catalog) | {name for name, _module in SECRET_OWNERS}

    if not SECRETS_DIR.exists():
        print(f"  {SECRETS_DIR} doesn't exist here — nothing to check")
        return

    on_disk = sorted(p.name for p in SECRETS_DIR.iterdir() if p.is_file())
    stale_vault_backed = [name for name in on_disk if name in vault_backed_scope]
    orphans = [name for name in on_disk if name not in known]

    if not stale_vault_backed and not orphans:
        print(f"  {len(on_disk)} file(s) on disk, all belong to a permanent file-cache entry — nothing to clean up")
        return

    if stale_vault_backed:
        print(
            f"  {len(stale_vault_backed)} file(s) for a Vault-backed entry — "
            "unread since it moved to Vault, not confirmed against Vault by this check (no credentials needed for --local):"
        )
        for name in stale_vault_backed:
            print(f"    {name}  (scope: {vault_backed_scope[name]})")
        print("\n  Confirm each has a real value in Vault before deleting (e.g. openbao_utils/bootstrap.py")
        print("  reports it as already-set, or a direct kv get) — then: rm " + " ".join(f"ansible/files/secrets/{n}" for n in stale_vault_backed))

    if orphans:
        print(f"\n  {len(orphans)} file(s) not referenced by current config at all:")
        for name in orphans:
            print(f"    {name}")
        print("\n  Not deleted — confirm these aren't referenced by a branch/host you haven't")
        print("  checked, then: rm " + " ".join(f"ansible/files/secrets/{n}" for n in orphans))


# --- OCI: list customer secret keys per leaf (via SCIM - see ADR 0016) ----


def audit_oci() -> None:
    print("\n== OCI customer secret keys (write + read leaves) ==")

    try:
        client = oci_identity_domains_client()
    except SystemExit:
        # require_secret() already printed what's missing and why.
        return

    for leaf in ("write", "read"):
        user_id = read_secret(f"_oci-leaf-user-ocid-{leaf}")
        active_scim_id = read_secret(f"oci-{leaf}-scim-id")
        if not user_id:
            print(f"  {leaf}: no cached user OCID, skipping")
            continue
        keys = client.list_customer_secret_keys(filter=f'user.ocid eq "{user_id}"').data.resources or []
        print(f"  {leaf}-leaf user has {len(keys)} customer secret key(s) (OCI allows max 2):")
        for key in keys:
            marker = "ACTIVE (matches cache)" if key.id == active_scim_id else "ORPHAN"
            created = (key.meta.created if key.meta else None) or "unknown"
            print(f"    scim_id={key.id}  accessKey={key.access_key}  created={created}  status={key.status or 'unknown'}  [{marker}]")
            if marker == "ORPHAN":
                print(f"      delete: DELETE {client.base_client.endpoint}/admin/v1/CustomerSecretKeys/{key.id}")
                print(f"      or Console: Identity & Security > Users > homelab-cloud-sync-{leaf} > Customer Secret Keys > Delete")


# --- B2: list keys via the rotation key -----------------------------------


def audit_b2() -> None:
    print("\n== B2 application keys (via rotation key) ==")
    try:
        keys = b2_list_keys(b2_rotation_api())
    except SystemExit:
        # require_secret() already printed what's missing and why.
        return

    rotation_key_id = read_secret("_rotation-key-backblaze-b2-key-id")
    active = {
        read_secret("backblaze-b2-write-access-key"): "write",
        read_secret("backblaze-b2-read-access-key"): "read",
        read_secret("backblaze-b2-openbao-snapshot-write-access-key"): "openbao snapshot write leaf",
        rotation_key_id: "rotation key",
    }
    print(f"  {len(keys)} key(s) on the account:")
    for key in keys:
        key_id = key.id_
        if key_id in active:
            marker = f"ACTIVE ({active[key_id]})"
        elif key.key_name == "openbao-snapshot-readonly":
            # ADR 0017: this credential is never cached anywhere by
            # design (create_snapshot_readonly_keys.py prints it once,
            # straight to the break-glass password-manager entry) - a
            # cache lookup can never confirm it, so this is matched by
            # its own known provider-side name instead. Weaker proof
            # than a cache match (a genuine orphan could reuse this
            # name), but this tool already only flags, never deletes -
            # see its own module docstring.
            marker = "ACTIVE (break-glass restore key, ADR 0017 - matched by name, not cache, since it's never cached)"
        else:
            marker = "ORPHAN"
        print(f"    {key_id}  name={key.key_name}  [{marker}]")
        if marker == "ORPHAN":
            print(f"      delete: b2_delete_key with applicationKeyId={key_id}")
            print("      or Console: App Keys > find this key ID > Delete")


# --- R2: list account-owned tokens -----------------------------------------


def audit_r2() -> None:
    print("\n== Cloudflare R2 account-owned API tokens ==")
    account_id = read_secret("cloudflare-r2-account-id")
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
        read_secret("cloudflare-r2-write-access-key"): "write",
        read_secret("cloudflare-r2-read-access-key"): "read",
        read_secret("cloudflare-r2-openbao-snapshot-write-access-key"): "openbao snapshot write leaf",
    }
    # Both openbao-snapshot tokens (write and the break-glass readonly)
    # use their own fixed names, not the "homelab-cloud-sync-r2-<leaf>"
    # pattern cloud_sync's own leaves get (create_snapshot_write_keys.py's
    # TOKEN_NAME_R2, create_snapshot_readonly_keys.py's own token_name) -
    # excluding them from this filter meant neither ever showed up here
    # at all, orphan or not.
    tokens = [
        t for t in body["result"] if t["name"].startswith("homelab-cloud-sync-r2-") or t["name"] in ("openbao-snapshot-write", "openbao-snapshot-readonly")
    ]
    print(f"  {len(tokens)} homelab-cloud-sync-r2-*/openbao-snapshot-* token(s):")
    for t in tokens:
        if t["id"] in active:
            marker = f"ACTIVE ({active[t['id']]})"
        elif t["name"] == "openbao-snapshot-readonly":
            # ADR 0017: never cached anywhere by design - see audit_b2's
            # identical comment on why this is matched by name instead.
            marker = "ACTIVE (break-glass restore key, ADR 0017 - matched by name, not cache, since it's never cached)"
        else:
            marker = "ORPHAN"
        print(f"    {t['id']}  name={t['name']}  status={t['status']}  [{marker}]")
        if marker == "ORPHAN":
            print(f"      delete: DELETE https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens/{t['id']}")
            print("      or Dashboard: Manage Account > Account API Tokens > find this token > Delete")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", help="audit only the controller-side file cache, ansible/files/secrets/ (default if no --provider)")
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
