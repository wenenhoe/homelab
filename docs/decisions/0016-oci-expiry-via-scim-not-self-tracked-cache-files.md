# 0016. OCI credential expiry via Identity Domains SCIM, not self-tracked cache files

**Status:** Accepted

## Context

[0015](0015-credential-expiry-native-where-possible-self-tracked-where-not.md)
shipped self-tracked `-created-at` cache files for OCI's leaf keys and
rotation keypair, because the classic Identity API this repo calls has
no expiry field at all, and scoped a SCIM-based alternative out as a
second, unrelated auth integration not worth building speculatively.

That integration has now been built as a throwaway spike
(`cloud_credentials/spikes/oci_scim_oauth_check.py`) and run live
against this tenancy, confirming what 0015 could only note as
theoretically possible:

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
- The Confidential Application's own OAuth2 client secret
  (`oci.identity_domains.models.OAuth2ClientCredential`) has a native
  `expires_on` of its own. The short-lived access token minted per run
  is never itself cached or rotated — only the client ID + secret is
  the long-lived credential, playing the role the current rotation
  keypair plays today.

This replaces the auth/IAM model for OCI expiry tracking: a
Confidential Application (client ID + secret, authorizing via a domain
app role) instead of the OCID + PEM keypair authorizing via a classic
compartment policy statement. It does not yet resolve whether creating
a `CustomerSecretKey` via SCIM also produces the actual usable
access-key/secret-key material (in which case SCIM create could
replace the classic API's create call for OCI leaf keys and the
rotation keypair too), or whether it only manages `expiresOn` metadata
on a key still created classic-API-side — the spike's create response
was only checked for `id` and `expiresOn`, not for key material. That
distinction changes the shape of the implementation but not this
decision: either way, the Confidential App + OAuth2 flow described
above is required to read or set native expiry at all.

## Decision

OCI leaf-key and rotation-keypair expiry moves from self-tracked
`-created-at` cache files to native `expiresOn`, read and set via the
Identity Domains SCIM API, authenticated with a Confidential
Application's OAuth2 client credentials. This supersedes only the OCI
portion of 0015 — B2's and R2's native handling is unaffected.

## Consequences

- Whether the SCIM `CustomerSecretKey` create call replaces classic
  API's `CreateCustomerSecretKeyDetails` call (SCIM does everything) or
  only adds expiry on top of it (classic API still creates the key,
  SCIM sets/reads `expiresOn`) is still open and blocks writing
  implementation code — one more live check, not a re-scope, resolves
  it.
- Once built, OCI joins B2/R2 in having zero self-tracked cache files
  for expiry — the last gap 0015 left open closes.
- A new long-lived credential is introduced (the Confidential
  Application's client ID + secret) to replace the role the OCI
  rotation keypair plays today; the keypair itself may become
  redundant depending on how the open question above resolves.
- The classic-API code path (`leaf_keys/oci.py`,
  `rotation_keys/oci_bootstrap.py`) stays as-is until the SCIM path is
  fully built and cut over — not touched by this decision alone.

See `cloud-credential-creation.md`'s Credential expiry section (once
updated) for the resulting setup/verification steps.
