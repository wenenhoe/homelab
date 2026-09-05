#!/usr/bin/env python3
"""Mint the read-only cloud credential ADR 0017 calls for: scoped to
OpenBao's own raft-snapshot bucket, able to fetch a snapshot but nothing
else, and — unlike every credential create_leaf_keys.py handles — never
written to ansible/files/secrets/ at all. That cache is exactly the
mechanism this migration retires; a credential meant to survive `security`
being rebuilt from nothing can't depend on a file that (a) lives on the
same class of host as the thing being rebuilt and (b) stops existing once
Track A's cutover stage deletes it. Instead this script prints the
credential once and exits — the operator copies it straight into the
password manager entry that already holds the Shamir unseal shares (see
docs/openbao.md), same offline handling this repo already gives the
backup GPG key (docs/disaster-recovery.md).

Two providers, not one — R2 and B2, per docs/openbao.md — so recovery
doesn't depend on a single cloud vendor being reachable. Both point at a
bucket dedicated to OpenBao's own snapshots (openbao-snapshots /
openbao-snapshots-b2), separate from homelab-backups/-b2: the existing
per-app backup bucket is written to by every app host's backup_agent
(see docs/disaster-recovery.md's threat model), and this credential's
whole point is to keep working even if that path is compromised.

Create the bucket by hand first, same as homelab-backups/-b2 (see
docs/cloud-sync.md's Setup section) — this script doesn't create buckets,
only credentials. Authenticates using the same cached rotation
credentials create_leaf_keys.py already uses (b2_rotation_session,
r2_rotation_token) — those still live in the file cache at the point
this runs (Track A hasn't cut over to Vault-only yet), so reusing them
here doesn't create a new dependency.

No native or self-tracked expiry, deliberately: this credential isn't
part of the quarterly leaf-rotation cycle create_leaf_keys.py drives
(nothing here re-mints or refreshes it), it lives offline like the GPG
key (`expiration: 0` there too), and check_freshness.py has no cache
file to alert on since one was never written. Re-run this script by hand
if you ever want to replace it — same discipline as regenerating the
GPG key.

Usage (run from ansible/):
    python3 -m cloud_credentials.create_snapshot_readonly_keys [--provider {r2,b2,all}]
"""

from __future__ import annotations

import argparse
import hashlib
import sys

import requests

from cloud_credentials.cache import require_cache_file
from cloud_credentials.leaf_keys.b2 import B2_LEAF_CAPABILITIES, b2_lookup_bucket_id, b2_rotation_session
from cloud_credentials.leaf_keys.r2 import r2_create_leaf_token, r2_permission_group_ids, r2_rotation_token

SNAPSHOT_BUCKET_R2 = "openbao-snapshots"
SNAPSHOT_BUCKET_B2 = "openbao-snapshots-b2"


def mint_r2() -> None:
    token = r2_rotation_token()
    account_id = require_cache_file(
        "cloudflare-r2-account-id",
        "Already required for cloud-sync.md's endpoint — same file, no new step.",
    )
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    group_by_name = r2_permission_group_ids(session, account_id)

    result = r2_create_leaf_token(
        session,
        account_id,
        group_by_name,
        "read",
        bucket=SNAPSHOT_BUCKET_R2,
        token_name="openbao-snapshot-readonly",  # noqa: S106 - a display label for the token, not the token value itself
        native_expiry=False,
    )
    print("\n--- R2: openbao-snapshot-readonly ---")
    print(f"  bucket:       {SNAPSHOT_BUCKET_R2}")
    print(f"  access key:   {result['id']}")
    # Cloudflare's own docs: Secret Access Key = SHA-256 hash of the
    # token value, computed locally (see leaf_keys/r2.py's create_r2 for
    # the same derivation on cloud_sync's own leaves).
    print(f"  secret key:   {hashlib.sha256(result['value'].encode()).hexdigest()}")
    print("  Copy both into the break-glass password manager entry now — not written to disk anywhere.")


def mint_b2() -> None:
    session, account_id, api_url = b2_rotation_session()
    bucket_id = b2_lookup_bucket_id(session, api_url, account_id, bucket_name=SNAPSHOT_BUCKET_B2)
    body = session.post(
        f"{api_url}/b2api/v2/b2_create_key",
        json={
            "accountId": account_id,
            "capabilities": B2_LEAF_CAPABILITIES["read"],
            "keyName": "openbao-snapshot-readonly",
            "bucketId": bucket_id,
            # No validDurationInSeconds — see module docstring.
        },
    )
    body.raise_for_status()
    key_body = body.json()
    print("\n--- B2: openbao-snapshot-readonly ---")
    print(f"  bucket:       {SNAPSHOT_BUCKET_B2}")
    print(f"  key id:       {key_body['applicationKeyId']}")
    print(f"  app key:      {key_body['applicationKey']}")
    print("  Copy both into the break-glass password manager entry now — not written to disk anywhere.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["r2", "b2", "all"], default="all")
    args = parser.parse_args()

    mint_fns = {"r2": mint_r2, "b2": mint_b2}
    targets = mint_fns if args.provider == "all" else {args.provider: mint_fns[args.provider]}
    for name, fn in targets.items():
        try:
            fn()
        except requests.HTTPError as exc:
            print(f"{name}: request failed: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
