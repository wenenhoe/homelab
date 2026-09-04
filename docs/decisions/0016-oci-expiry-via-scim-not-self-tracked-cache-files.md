# 0016. OCI credential expiry via Identity Domains SCIM, not self-tracked cache files

**Status:** Accepted

## Context

[0015](0015-credential-expiry-native-where-possible-self-tracked-where-not.md)
shipped self-tracked `-created-at` cache files for OCI's leaf keys and
rotation keypair, because the classic Identity API this repo calls has
no expiry field at all, and scoped a SCIM-based alternative out as a
second, unrelated auth integration not worth building speculatively.

That integration has been built and confirmed live against this
tenancy (`cloud_credentials/spikes/oci_scim_oauth_check.py` and
`oci_scim_app_secret_check.py`), then implemented as the real
`leaf_keys/oci.py` and `rotation_keys/oci_bootstrap.py`, confirming
what 0015 could only note as theoretically possible:

- A Confidential Application with OAuth2 client-credentials, granted
  the **User Administrator** domain app role, successfully
  authenticates against the Identity Domain's SCIM endpoint and can
  call `POST /admin/v1/CustomerSecretKeys`.
- `expiresOn` on that resource is `mutability: immutable` per Oracle's
  own schema reference — settable at create, and confirmed live to
  round-trip as the same instant (OCI echoes it back with explicit
  milliseconds even when the request sent none; a naive string
  comparison misreads that as a mismatch, an instant comparison
  doesn't).
- The `user` sub-object takes the target user's OCID in its `ocid`
  field, not `value` — `value` is a shorter, unrelated SCIM-internal
  id capped at 40 characters and rejects an OCID outright. Confirmed
  live, not inferred from the schema's `maxLength` alone.
- The Confidential Application's own client secret has **no native
  expiry of its own** — confirmed against Oracle's own SDK model for
  the `App` resource (no `expires_on`/`expiresOn` field anywhere on
  it). `oci.identity_domains.models.OAuth2ClientCredential` looked
  like a candidate but is a different, unrelated resource: it's scoped
  to a `user`, not to an App, and has nothing to do with the client
  credentials this repo's own Confidential Application authenticates
  with. Regenerating an App's client secret (`POST
  /admin/v1/AppClientSecretRegenerator`) is also a hard cutover, not an
  overlap window — confirmed via Oracle's own product-feedback forum,
  where "support multiple active client secrets" is an open feature
  request, i.e. today there is exactly one active secret per App and
  regenerating invalidates the old one immediately.

This replaces the auth/IAM model for OCI expiry tracking: a
Confidential Application (client ID + secret, authorizing via a domain
app role) instead of the OCID + PEM keypair authorizing via a classic
compartment policy statement. It also replaces creation: `accessKey`
and `secretKey` on the SCIM `CustomerSecretKey` resource are both
`mutability: readOnly, returned: default` per Oracle's own schema
reference, and confirmed live to actually come back populated on
create — SCIM's create call generates a genuine, usable key pair, not
metadata bolted onto a key still created classic-API-side.

## Decision

OCI leaf-key creation *and* expiry both move to the Identity Domains
SCIM API, authenticated with a Confidential Application's OAuth2
client credentials — replacing the classic API's
`CreateCustomerSecretKeyDetails` call entirely, not just adding
`expiresOn` on top of it. The rotation credential itself changes shape
(a Confidential Application's client ID + secret, replacing the OCID +
PEM keypair) but keeps a self-tracked cache-file timestamp, since
neither has native expiry. This supersedes only the OCI portion of
0015 — B2's and R2's native handling is unaffected.

## Consequences

- OCI's **leaf keys** join B2/R2 in having zero self-tracked cache
  files for expiry. The rotation credential is a different story:
  since the Confidential Application's client secret has no native
  expiry (see Context), it still needs a self-tracked cache-file
  timestamp — the same shape 0015 used for the OCID+PEM keypair, just
  for a different credential. 0015's gap narrows here, it doesn't
  fully close.
- A new long-lived credential replaces the role the old OCI rotation
  keypair played; the keypair itself is gone (removed along with
  `oci_ensure_rotation_identity` and `_verify_rotation_key` — there is
  no classic-IAM rotation identity for OCI anymore).
- Regenerating the Confidential Application's own client secret is a
  hard cutover, not an overlap window (see Context) — unlike leaf-key
  rotation, there's no verify-before-revoke available for this specific
  credential; a regeneration that turns out broken has no old secret
  left to fall back to. `rotation_keys/oci_bootstrap.py:rotate_oci_rotation_key`
  caches the new secret immediately once returned, before attempting
  to verify it, since the old one is already gone regardless of that
  outcome.
- `audit_secrets.py --provider oci` also moved to SCIM
  (`GET /admin/v1/CustomerSecretKeys?filter=user.ocid eq "..."`,
  confirmed to work live) — the last place this repo's OCI tooling
  still touched `~/.oci/config` for anything customer-secret-key
  related. `~/.oci/config` is still required, but only for
  leaf-identity classic-IAM bootstrapping (`oci_ensure_leaf_identity`),
  which this decision never touched.
- The classic-API code path this superseded
  (`oci_ensure_rotation_identity`, `_verify_rotation_key`, and the
  RSA-keypair generation in both `leaf_keys/oci.py` and
  `rotation_keys/oci_bootstrap.py`) has been removed, not left
  alongside the new path.

See `cloud-credential-creation.md`'s Credential expiry section for the
resulting setup/verification steps.
