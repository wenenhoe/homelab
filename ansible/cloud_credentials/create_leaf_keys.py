#!/usr/bin/env python3
"""Create the 6 cloud_sync credentials (write+read x R2/B2/OCI) via each
provider's HTTP API instead of a console click-through, and cache them at
the same ansible/files/secrets/<registry-key> paths bootstrap_secrets.py
would have written by hand. Entries stay format: manual in
secrets_registry.yaml — this script is just an automated way to fill
them in. See docs/cloud-credential-creation.md for the exact grant
each leaf gets, provider-by-provider.

B2 and OCI authenticate using a rotation-key credential — narrower
than the account's master credential, created once by
create_rotation_keys.py — never the raw master key itself. If a
rotation-key cache file is missing for either, this script tells you
which `create_rotation_keys --provider <x>` to run first.

R2 caches its admin token too (r2_rotation_token), but it's a
materially different credential than B2's/OCI's rotation keys: it can
mint a token with ANY permission the account holder has, not just
R2-scoped ones, because Cloudflare has no equivalent of "manage tokens
but only for R2 permissions" (confirmed live: the tokens API rejects
granting token-management permission to any API-created token, so this
can only be a human-created Console token in the first place — caching
it doesn't change what it can do, only how often you have to paste it
in). This is a deliberate, accepted risk — see
docs/cloud-credential-creation.md's R2 section for the trade-off and
what's expected to narrow it later (a secrets-manager migration, not
this script).

Safe to re-run: a credential whose both cache files already exist is
left untouched, same convention as bootstrap_secrets.py.

To rotate a leaf key with verify-before-revoke of the old one (the new
key must actually pass a live read/write check over the same rclone
S3-compatible path production uses before the old key is touched), use
--rotate instead of deleting cache files for all three providers now —
see docs/cloud-credential-creation.md's Rotation section.

Usage (run from ansible/):
    python3 -m cloud_credentials.create_leaf_keys [--provider {r2,b2,oci,all}]
    python3 -m cloud_credentials.create_leaf_keys --provider {r2,b2,oci} --rotate {write,read,both}
"""

from __future__ import annotations

import argparse
import sys

import requests

from cloud_credentials.cache import SECRETS_DIR
from cloud_credentials.leaf_keys.b2 import create_b2, rotate_b2
from cloud_credentials.leaf_keys.oci import create_oci, rotate_oci
from cloud_credentials.leaf_keys.r2 import create_r2, rotate_r2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["r2", "b2", "oci", "all"], default="all")
    parser.add_argument(
        "--rotate",
        choices=["write", "read", "both"],
        help=(
            "Rotate a leaf key: create a new one, verify it over the same rclone "
            "S3-compatible path production uses, only then revoke the old one. "
            "Requires --provider r2, b2, or oci (not all) — see this script's "
            "module docstring."
        ),
    )
    args = parser.parse_args()

    SECRETS_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)

    if args.rotate:
        if args.provider not in ("r2", "b2", "oci"):
            parser.error("--rotate requires --provider r2, b2, or oci")
        leaves = ["write", "read"] if args.rotate == "both" else [args.rotate]
        rotate_fn = {"r2": rotate_r2, "b2": rotate_b2, "oci": rotate_oci}[args.provider]
        try:
            ok = rotate_fn(leaves)
        except requests.HTTPError as exc:
            print(f"{args.provider}: request failed: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
            return 1
        return 0 if ok else 1

    providers = {"r2": create_r2, "b2": create_b2, "oci": create_oci}
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
