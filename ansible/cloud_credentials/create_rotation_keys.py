#!/usr/bin/env python3
"""One-time-per-rotation-key bootstrap: take each provider's master
credential in memory only (never written to disk, never logged) and use
it to mint a narrower "rotation key" that can create/delete the leaf
keys but can't touch backup data itself. create_leaf_keys.py
authenticates with the cached rotation key from here on — the master
credential is never read by that script.

R2 has no equivalent to mint via API — confirmed live, not an
oversight: Cloudflare rejects granting "manage other tokens" permission
to any token created via the API, so no delegate credential can ever be
minted for R2. --provider r2 here doesn't create anything; it only
caches (or re-caches) the Custom Token a human creates in the Console.
See docs/cloud-credential-creation.md's R2 section.

See docs/cloud-credential-creation.md for what each remaining
provider's rotation key is actually scoped to (the achievable floor
differs a lot by provider — OCI has real, documented limits on how far
this can be narrowed, not a uniform "create/delete keys only"
guarantee).

Without --rotate: idempotent bootstrap. Re-verifies/repairs IAM
policies (OCI) against an already-cached keypair every run, but never
regenerates the keypair itself if its cache files already exist (or,
for R2, never re-prompts if a token is already cached) — safe to
re-run at any time, including against a rotation key that's already
expiring, without accidentally reissuing it. --provider r2 is never
included in --provider all, since it blocks on a Console step the
operator may not have done yet — it has to be requested explicitly.

With --rotate: for b2/oci, mints a genuinely new rotation key,
verifies it can actually do its job, only then revokes the old one —
the only path that reissues an already-existing rotation key with
fresh expiry. For r2, there's nothing to verify or revoke via API —
this just re-prompts for the Console-created token and overwrites the
cache unconditionally, since rolling it in the Console already revokes
the old one before this ever runs. Requires --provider b2, oci, or r2
(not all).

Usage (run from ansible/):
    python3 -m cloud_credentials.create_rotation_keys [--provider {b2,oci,all}]
    python3 -m cloud_credentials.create_rotation_keys --provider r2
    python3 -m cloud_credentials.create_rotation_keys --provider {b2,oci,r2} --rotate
"""

from __future__ import annotations

import argparse
import sys

import requests

from cloud_credentials.cache import SECRETS_DIR
from cloud_credentials.rotation_keys.b2 import create_b2_rotation_key, rotate_b2_rotation_key
from cloud_credentials.rotation_keys.oci_bootstrap import create_oci_rotation_key, rotate_oci_rotation_key
from cloud_credentials.rotation_keys.r2 import cache_r2_rotation_token, rotate_r2_rotation_token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["b2", "oci", "r2", "all"], default="all")
    parser.add_argument(
        "--admin-email",
        help=(
            "Required for --provider oci/all. One real mailbox you control — "
            "each OCI service user gets a +tag off it "
            "(you+homelab-cloud-sync-write@domain, etc.), since "
            "Identity-Domain-enabled tenancies require a unique email per user."
        ),
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help=(
            "Reissue an already-existing rotation key/token. For b2/oci: mint "
            "new, verify it can actually do its job, only then revoke the old "
            "one. For r2: no verify-then-revoke is possible — just re-prompts "
            "and overwrites the cache. Requires --provider b2, oci, or r2 "
            "(not all)."
        ),
    )
    args = parser.parse_args()

    if args.provider in ("oci", "all") and not args.admin_email:
        parser.error("--admin-email is required for --provider oci (your tenancy's Identity Domains require a unique email per OCI user)")

    if args.rotate and args.provider not in ("b2", "oci", "r2"):
        parser.error("--rotate requires --provider b2, oci, or r2")

    SECRETS_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)

    if args.rotate:
        rotate_fn = {
            "b2": rotate_b2_rotation_key,
            "oci": lambda: rotate_oci_rotation_key(args.admin_email),
            "r2": rotate_r2_rotation_token,
        }[args.provider]
        try:
            ok = rotate_fn()
        except requests.HTTPError as exc:
            print(f"{args.provider}: request failed: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
            return 1
        return 0 if ok else 1

    if args.provider == "r2":
        cache_r2_rotation_token()
        return 0

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
