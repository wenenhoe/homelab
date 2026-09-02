#!/usr/bin/env python3
"""One-time-per-rotation-key bootstrap: take each provider's master
credential in memory only (never written to disk, never logged) and use
it to mint a narrower "rotation key" that can create/delete the leaf
keys but can't touch backup data itself. create_leaf_keys.py
authenticates with the cached rotation key from here on — the master
credential is never read by that script.

R2 has no provider here at all — confirmed live, not an oversight:
Cloudflare rejects granting "manage other tokens" permission to any
token created via the API, so no delegate credential can ever be
minted for R2. Its master token is prompted directly by
create_leaf_keys.py instead, in memory only, every time it's actually
needed. See docs/cloud-credential-creation.md's R2 section.

See docs/cloud-credential-creation.md for what each remaining
provider's rotation key is actually scoped to (the achievable floor
differs a lot by provider — OCI has real, documented limits on how far
this can be narrowed, not a uniform "create/delete keys only"
guarantee).

Run this again when a rotation key itself needs rotating, or to
re-verify/repair IAM policies (OCI) against an already-cached keypair —
neither regenerates the keypair unless its cache files are missing.
Routine leaf-key rotation is create_leaf_keys.py's job and doesn't
touch this script or the master credential at all.

Usage (run from ansible/):
    python3 -m cloud_credentials.create_rotation_keys [--provider {b2,oci,all}]
"""
from __future__ import annotations

import argparse
import sys

import requests

from cloud_credentials.cache import SECRETS_DIR
from cloud_credentials.rotation_keys.b2 import create_b2_rotation_key
from cloud_credentials.rotation_keys.oci_bootstrap import create_oci_rotation_key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["b2", "oci", "all"], default="all")
    parser.add_argument(
        "--admin-email",
        help=(
            "Required for --provider oci/all. One real mailbox you control — "
            "each OCI service user gets a +tag off it "
            "(you+homelab-cloud-sync-write@domain, etc.), since "
            "Identity-Domain-enabled tenancies require a unique email per user."
        ),
    )
    args = parser.parse_args()

    if args.provider in ("oci", "all") and not args.admin_email:
        parser.error(
            "--admin-email is required for --provider oci (your tenancy's "
            "Identity Domains require a unique email per OCI user)"
        )

    SECRETS_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)

    providers = {
        "b2": create_b2_rotation_key,
        "oci": lambda: create_oci_rotation_key(args.admin_email),
    }
    targets = providers if args.provider == "all" else {args.provider: providers[args.provider]}
    for name, fn in targets.items():
        try:
            fn()
        except requests.HTTPError as exc:
            print(f"{name}: request failed: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
