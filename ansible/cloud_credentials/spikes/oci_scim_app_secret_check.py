#!/usr/bin/env python3
"""Spike, but NOT throwaway/reversible like the others in this
directory: this permanently regenerates the Confidential Application's
own client secret. See ADR 0016's Consequences - Oracle's own
product-feedback forum confirms there is exactly one active secret per
App, and regenerating invalidates the old one immediately. There is no
create-then-verify-then-delete pattern possible here, unlike every
other credential this repo rotates.

What this settles: two things ADR 0016 left open.

1. Oracle's own AppRole-to-endpoint tables list `Apps` (search) and
   `AppClientSecretRegenerator` under the Security Administrator app
   role, not User Administrator (the role already granted for
   CustomerSecretKeys work). Untested whether User Administrator alone
   is enough, or whether Security Administrator needs adding too. If
   this 403s, add Security Administrator to the app's Token Issuance
   Policy in Console and re-run.
2. The exact schema URN for AppClientSecretRegenerator isn't spelled
   out anywhere in Oracle's own docs pages (unlike customerSecretKey's,
   which is). ID_SCHEMA_GUESS below follows the same
   urn:ietf:params:scim:schemas:oracle:idcs:<ResourceName> pattern that
   held for customerSecretKey - if it's wrong, the 400 body will name
   the actual schema this tenancy expects.

Sequence: authenticate with the OLD secret (from cache) -> search
/admin/v1/Apps by displayName for this app's own SCIM id -> POST
/admin/v1/AppClientSecretRegenerator -> the OLD secret is dead the
instant that call succeeds -> the NEW secret is cached immediately
(never printed - see below), before verification, since it's the only
copy of a value OCI shows exactly once and the OLD secret is gone
either way -> only then does this script re-authenticate with the NEW
secret as a diagnostic check, not a gate on caching it.

If the verification re-authentication fails: the NEW secret is
already cached, but this script can't confirm it actually works. The
OLD secret is gone regardless - there is no rollback available here.
Check the cached value by hand (or use Console's own "Regenerate"
button to get a fresh one) rather than assume it's fine.

The new secret is never printed - only its length - since this
script's output tends to get pasted into chat. It's written straight
to the same cache file leaf_keys/oci.py and rotation_keys/oci_bootstrap.py
already read.

Usage (run from ansible/):
    python3 -m cloud_credentials.spikes.oci_scim_app_secret_check \
        <app_display_name>
Reads domain_url/client_id/old client_secret from the same
_rotation-key-oci-* cache files oci_scim.py already uses - nothing new
to type in for those.
"""

from __future__ import annotations

import sys

from cloud_credentials.cache import write_cache
from cloud_credentials.expiry import utcnow_iso
from cloud_credentials.rotation_keys.oci_scim import oci_scim_access_token, oci_scim_domain_and_credentials, oci_scim_session

# Unconfirmed - see module docstring point 2. A wrong guess here
# surfaces as a 400 naming the schema this tenancy actually expects,
# not a silent failure.
APP_CLIENT_SECRET_REGENERATOR_SCHEMA_GUESS = "urn:ietf:params:scim:schemas:oracle:idcs:AppClientSecretRegenerator"  # noqa: S105 - a schema URN, not a credential


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <app_display_name>", file=sys.stderr)
        return 2
    app_display_name = argv[1]

    try:
        session, domain_url = oci_scim_session()
    except (SystemExit, Exception) as exc:
        print(f"\nAuthenticating with the OLD secret: FAILED ({exc})", file=sys.stderr)
        return 1
    print("Authenticating with the OLD secret: succeeded")

    search_resp = session.get(f"{domain_url}/admin/v1/Apps", params={"filter": f'displayName eq "{app_display_name}"'})
    if search_resp.status_code != 200:
        print(f"\nApp search FAILED ({search_resp.status_code} {search_resp.text})", file=sys.stderr)
        print(
            "A 403 here (with a working OLD-secret token above) most likely means the "
            "granted app role doesn't cover Apps search - try adding Security "
            "Administrator to this app's Token Issuance Policy in Console.",
            file=sys.stderr,
        )
        return 1
    resources = search_resp.json().get("Resources", [])
    if not resources:
        print(f"\nNo app found with displayName={app_display_name!r} - check the exact name in Console.", file=sys.stderr)
        return 1
    app_id = resources[0]["id"]
    print(f"App search: succeeded (id={app_id})")

    regen_body = {"schemas": [APP_CLIENT_SECRET_REGENERATOR_SCHEMA_GUESS], "appId": app_id}
    regen_resp = session.post(f"{domain_url}/admin/v1/AppClientSecretRegenerator", json=regen_body)
    if regen_resp.status_code not in (200, 201):
        print(f"\nAppClientSecretRegenerator FAILED ({regen_resp.status_code} {regen_resp.text})", file=sys.stderr)
        print(
            "The OLD secret is still valid - nothing was invalidated by a failed "
            "request. A 403 here likely means Security Administrator (or another "
            "role covering AppClientSecretRegenerator) isn't granted yet. A 400 "
            "naming the schema may mean APP_CLIENT_SECRET_REGENERATOR_SCHEMA_GUESS "
            "in this script is wrong - the error body should say what's expected.",
            file=sys.stderr,
        )
        return 1

    new_secret = regen_resp.json().get("clientSecret")
    if not new_secret:
        print(
            "\nCRITICAL: AppClientSecretRegenerator succeeded but returned no "
            "clientSecret. The OLD secret is now invalid and this script has no "
            "new one to fall back to. Use Console's own Regenerate button now.",
            file=sys.stderr,
        )
        return 1
    print(f"AppClientSecretRegenerator: succeeded (new secret is {len(new_secret)} chars, not printed)")

    # Cached immediately, before verification - this IS the current
    # live secret regardless of whether the verification round-trip
    # below succeeds. Withholding the cache write on a verification
    # failure (which could be transient/unrelated to whether the
    # secret itself works) would throw away the only copy of a secret
    # OCI shows exactly once, for no good reason: the OLD secret is
    # already gone either way.
    write_cache("_rotation-key-oci-client-secret", new_secret)
    write_cache("_rotation-key-oci-app-id", app_id)
    # Self-tracked, not native (see ADR 0016's Context: the App
    # resource has no expires_on field of its own) - same role this
    # cache file played for the old OCID+PEM keypair.
    write_cache("_rotation-key-oci-created-at", utcnow_iso())

    # The OLD secret is dead from this point on, regardless of what
    # happens next - this is the hard-cutover ADR 0016 describes.
    domain_url_only, client_id, _old_secret = oci_scim_domain_and_credentials()
    try:
        oci_scim_access_token(domain_url_only, client_id, new_secret)
    except Exception as exc:
        print(
            f"\nNew secret is cached, but verifying it with a fresh token exchange "
            f"FAILED ({exc}). The OLD secret is already invalidated regardless. "
            f"Check the cached value by hand before relying on it.",
            file=sys.stderr,
        )
        return 1
    print("Re-authenticating with the NEW secret: succeeded")
    print("\nNew client secret cached and confirmed working. Old secret is permanently invalid as of the regenerate call above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
