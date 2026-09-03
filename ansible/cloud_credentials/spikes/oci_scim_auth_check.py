#!/usr/bin/env python3
"""Spike, not a supported CLI: does `OCISigner` (Signature V1) even
authenticate against OCI's Identity Domains SCIM API? That's the
load-bearing unknown from ADR 0015 - if it doesn't, moving OCI's
expiry onto the SCIM `expiresOn` field means adding a second auth
mechanism alongside the Signer this repo already uses, not just
pointing the existing calls at a different endpoint.

Purely read-only and throwaway: fetches `/admin/v1/Schemas`, a SCIM
resource that only describes the API's own schema shape - no user
data, no secret keys - using the SAME cached rotation identity's
signer `create_rotation_keys.py` already provisioned for the classic
API. Creates, rotates, and caches nothing; safe to run any number of
times against a real tenancy.

You supply the domain URL yourself - see Oracle's own "Finding an
Identity Domain URL" doc, or `oci iam domain list --compartment-id
<tenancy-ocid>`'s `url` field on each result. Not looked up
automatically here: that would need its own permission check on the
rotation identity (ListDomains isn't covered by its current `manage
users` policy statement - see rotation_keys/oci_bootstrap.py), which
is exactly the kind of speculative addition this script exists to
avoid making before the actual auth question below is answered.

Usage (run from ansible/):
    python3 -m cloud_credentials.spikes.oci_scim_auth_check \
        https://idcs-xxxxxxxxxxxx.identity.oraclecloud.com
"""

from __future__ import annotations

import sys

import requests

from cloud_credentials.leaf_keys.oci import oci_rotation_auth_and_endpoint


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} https://<domain-url>", file=sys.stderr)
        return 2
    domain_url = argv[1].rstrip("/")

    # oci_rotation_auth_and_endpoint()'s own `endpoint` return value is
    # the classic identity.{region}.oraclecloud.com URL - deliberately
    # discarded here. Only the signer is reused; the whole point of
    # this spike is testing that signer against a different endpoint.
    signer, _classic_endpoint = oci_rotation_auth_and_endpoint()

    url = f"{domain_url}/admin/v1/Schemas"
    resp = requests.get(url, auth=signer, timeout=45)

    print(f"GET {url}")
    print(f"status: {resp.status_code}")
    print(f"body (first 500 chars): {resp.text[:500]}")

    if resp.status_code == 200:
        print("\nSignature V1 auth against the SCIM endpoint: WORKS. Migrating to native expiresOn is a realistic follow-up.")
        return 0
    if resp.status_code in (401, 403):
        print(
            "\nSignature V1 auth against the SCIM endpoint: REJECTED. "
            "The rotation identity's existing signer doesn't carry over - "
            "a SCIM migration would need a second auth mechanism (likely "
            "OAuth2 client-credentials), not just a different endpoint. "
            "Update ADR 0015 with this finding either way.",
            file=sys.stderr,
        )
        return 1
    print(f"\nUnexpected status {resp.status_code} - inconclusive, investigate the body above before drawing a conclusion either way.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
