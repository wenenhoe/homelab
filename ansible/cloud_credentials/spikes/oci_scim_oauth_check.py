#!/usr/bin/env python3
"""Spike, not a supported CLI: the actual end-to-end unknown behind a
possible SCIM migration (see ADR 0015's OCI section and
oci_scim_auth_check.py, which already confirmed the *existing*
Signature V1 signer does NOT work here) — does OAuth2
client-credentials from a hand-registered Confidential Application
authenticate against Identity Domains SCIM, and does a real
POST /admin/v1/CustomerSecretKeys with `expiresOn` set actually persist
and read back that value?

Before running this: register a Confidential Application by hand in
the OCI Console (Identity Domains > your domain > Integrated
Applications > Add > Confidential Application), enable the "Client
credentials" grant type, and grant it an app role that can manage
customer secret keys via the admin API. Oracle's own docs (see
docs/cloud-credential-creation.md once this lands) document "User
Administrator" as sufficient for "query and manage users and groups"
generally, but NOT specifically confirmed for CustomerSecretKeys —
that's part of what this script tests. Note the Client ID and Client
Secret from the app's Configuration tab; this script never derives or
guesses them.

Token exchange (`POST {domain_url}/oauth2/v1/token`, Basic auth of
client_id:client_secret, `grant_type=client_credentials&scope=urn:opc:idm:__myscopes__`)
is confirmed against Oracle's own REST API and OCI IAM getting-started
docs, consistent across every worked example Oracle publishes for this
grant type — but never yet run against this tenancy's own app
registration and role grant, which is exactly what this script is for.

NOT purely read-only: creates one throwaway CustomerSecretKey on the
leaf user OCID you supply (with a 1-day `expiresOn`, to test that
field's round-trip too — confirmed via Oracle's own schema reference
that `expiresOn` is mutability:immutable, i.e. settable on create, not
server-computed), then deletes it immediately. The `user` sub-object
takes the OCID in its `ocid` field, not `value` — `value` is a
different, shorter SCIM-internal id (max 40 chars) and rejects an OCID
outright; confirmed live, not just from the schema's maxLength.
`expiresOn` itself is confirmed live to round-trip correctly as an
instant — OCI echoes it back with explicit milliseconds even when the
request omitted them, so the comparison here parses both sides as
timestamps rather than comparing strings.

Also checks whether `accessKey`/`secretKey` come back on the create
response — per Oracle's own SCIM schema reference, both are
mutability:readOnly, returned:default, meaning the server generates
them and returns them by default, the same shape as the classic API's
one-time-only secret disclosure. This resolves ADR 0016's open
question: if both are present, SCIM create produces a genuinely usable
credential and can replace the classic API's create call outright, not
just add expiry on top of it. Neither value is ever printed — only
presence and length, since this spike's output ends up pasted into
chat and possibly a terminal scrollback, and a throwaway key is still
a real, briefly-live credential until its delete call runs.

Safe to re-run: creates and deletes its own key each time, never
touches an existing one. No retry-on-401 loop here unlike
oci_bootstrap.py's key-propagation retries — that delay was confirmed
specifically for freshly-uploaded API signing keys under Signature V1,
not for OAuth2 tokens, and nothing here has confirmed the same class
of delay exists on this path. If a create or delete 401/403s once,
that's itself a data point — don't assume it's transient before
checking the response body.

Usage (run from ansible/):
    python3 -m cloud_credentials.spikes.oci_scim_oauth_check \
        https://idcs-xxxxxxxxxxxx.identity.oraclecloud.com \
        <client_id> \
        <leaf_user_ocid>
Client secret is prompted for, hidden, never cached.
"""

from __future__ import annotations

import base64
import getpass
import sys
from datetime import datetime

import requests

from cloud_credentials.expiry import rfc3339_in

SCIM_SCHEMA = "urn:ietf:params:scim:schemas:oracle:idcs:customerSecretKey"
THROWAWAY_DISPLAY_NAME = "homelab-scim-spike-throwaway"


def _get_access_token(domain_url: str, client_id: str, client_secret: str) -> str:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = requests.post(
        f"{domain_url}/oauth2/v1/token",
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        data={"grant_type": "client_credentials", "scope": "urn:opc:idm:__myscopes__"},
        timeout=45,
    )
    if resp.status_code != 200:
        raise requests.HTTPError(f"token exchange failed: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(f"usage: {argv[0]} https://<domain-url> <client_id> <leaf_user_ocid>", file=sys.stderr)
        return 2
    domain_url, client_id, leaf_user_ocid = argv[1].rstrip("/"), argv[2], argv[3]
    client_secret = getpass.getpass("Confidential Application client secret (hidden, not cached): ")

    try:
        token = _get_access_token(domain_url, client_id, client_secret)
    except (requests.HTTPError, requests.RequestException, KeyError) as exc:
        print(f"\nOAuth2 client-credentials token exchange: FAILED ({exc})", file=sys.stderr)
        print(
            "Check: 'Client credentials' grant enabled on the app, app role actually "
            "granted (Console changes to app role grants can take a minute to apply), "
            "client_id/secret copied correctly.",
            file=sys.stderr,
        )
        return 1
    print("OAuth2 client-credentials token exchange: succeeded")

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    session.headers["Content-Type"] = "application/scim+json"

    create_body = {
        "schemas": [SCIM_SCHEMA],
        "displayName": THROWAWAY_DISPLAY_NAME,
        "expiresOn": rfc3339_in(1),
        # `user.ocid` (maxLength 255), not `user.value` (maxLength 40,
        # SCIM's own short internal id, a different identifier than the
        # OCID) - confirmed live: sending the OCID as `value` 400s with
        # error.common.validation.stringExceedsMaxLimit. This script's
        # only user identifier is an OCID (from the classic API's own
        # cached _oci-leaf-user-ocid-*), so `ocid` is the only field
        # that fits it.
        "user": {"ocid": leaf_user_ocid},
    }
    create_resp = session.post(f"{domain_url}/admin/v1/CustomerSecretKeys", json=create_body, timeout=45)
    if create_resp.status_code not in (200, 201):
        print(f"\nSCIM CreateCustomerSecretKey: FAILED ({create_resp.status_code} {create_resp.text})", file=sys.stderr)
        print(
            "A 401/403 here (with a working token above) means the token's scope "
            "doesn't cover CustomerSecretKeys management — the app role grant is "
            "wrong or insufficient, not an auth problem in general.",
            file=sys.stderr,
        )
        return 1

    key = create_resp.json()
    key_id = key["id"]
    returned_expires_on = key.get("expiresOn")
    print(f"SCIM CreateCustomerSecretKey: succeeded (id={key_id})")

    # Presence/length only - never the value itself. See module
    # docstring: this is what resolves ADR 0016's open question about
    # whether SCIM create yields real, usable credential material.
    access_key, secret_key = key.get("accessKey"), key.get("secretKey")
    if access_key and secret_key:
        print(f"Live key material returned: accessKey present ({len(access_key)} chars), secretKey present ({len(secret_key)} chars)")
    else:
        print(
            f"Live key material NOT returned (accessKey present: {bool(access_key)}, "
            f"secretKey present: {bool(secret_key)}) — SCIM create looks metadata-only "
            f"here; a real key would still need the classic API's create call.",
            file=sys.stderr,
        )

    # Compared as instants, not strings: confirmed live that OCI echoes
    # expiresOn with explicit milliseconds (...50.000Z) even when the
    # request sent none (...50Z) - same instant, different string. A
    # naive string comparison here reports a false mismatch on every
    # single run.
    sent_instant = datetime.fromisoformat(create_body["expiresOn"].replace("Z", "+00:00"))
    returned_instant = datetime.fromisoformat(returned_expires_on.replace("Z", "+00:00")) if returned_expires_on else None
    if returned_instant == sent_instant:
        print(f"expiresOn round-trip: confirmed ({returned_expires_on})")
    else:
        print(
            f"expiresOn round-trip: MISMATCH — sent {create_body['expiresOn']!r}, "
            f"got back {returned_expires_on!r}. Don't assume the create-time value "
            f"is what's actually stored until this is explained.",
            file=sys.stderr,
        )

    delete_resp = session.delete(f"{domain_url}/admin/v1/CustomerSecretKeys/{key_id}", timeout=45)
    if delete_resp.status_code not in (200, 204):
        print(
            f"\nCleanup delete of throwaway key {key_id} FAILED "
            f"({delete_resp.status_code} {delete_resp.text}) — delete it by hand: "
            f"DELETE {domain_url}/admin/v1/CustomerSecretKeys/{key_id}",
            file=sys.stderr,
        )
        return 1
    print(f"Cleanup delete of throwaway key {key_id}: succeeded")

    print("\nEnd-to-end OAuth2 + SCIM CustomerSecretKey path: WORKS. See ADR 0016 for what this means for the migration decision.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
