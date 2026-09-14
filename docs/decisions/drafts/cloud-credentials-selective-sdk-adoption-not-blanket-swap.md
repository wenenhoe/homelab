# Adopt official SDKs in cloud_credentials selectively, not as a blanket swap

**Status:** Draft

## Context

Every module under `ansible/cloud_credentials/` talks to B2/R2/OCI
entirely over hand-rolled `requests` calls. The `oci` package is
already a pinned dependency (`oci.signer.Signer`,
`oci.config.from_file` — `rotation_keys/oci_iam.py`'s classic-IAM
bootstrap, per `cloud-credential-creation.md`), but the newer OCI SCIM
leaf/rotation flow (`leaf_keys/oci.py`, `rotation_keys/oci_bootstrap.py`,
`rotation_keys/oci_scim.py`, added by
[0016](../0016-oci-expiry-via-scim-not-self-tracked-cache-files.md))
reimplements the OAuth2 client-credentials exchange and every SCIM call
over raw `requests` instead of the same package's
`oci.identity_domains.IdentityDomainsClient`.

No retry/backoff exists for any of these calls today (`verify.py`'s
`rclone` retry logic is a separate matter — see
[`rclone-boto3-scope-not-blanket-swap.md`](rclone-boto3-scope-not-blanket-swap.md)).
Exception handling is also inconsistent: most `create_*`/`rotate_*`
call sites catch `requests.HTTPError` (raised only by
`.raise_for_status()`); `check_freshness.py` catches the broader
`requests.RequestException`.

Officially maintained clients exist for these targets: the `oci`
package already in use (its `identity_domains.IdentityDomainsClient` +
`ScimClientCredentials` model cover exactly the SCIM flow above),
`Backblaze/b2sdk` for B2 key management, and Cloudflare's official
Python SDK for R2's account API-token calls.

`cache.py`'s OpenBao KV v2 client (`hvac`) and its `_fetch_root_cert`
SSH call (`paramiko`) are **not** decided here — the same gap exists
independently in `bootstrap_secrets.py`, `audit_secrets.py`, and
`docker/openbao/watcher/r2_read_watcher.py`, so that question is scoped
across all four in
[`openbao-client-hvac-paramiko-adoption.md`](openbao-client-hvac-paramiko-adoption.md)
instead of just this package.

## Options

### A — Swap every raw `requests` call for its matching SDK, all at once

Removes hand-rolled JSON/auth boilerplate across every remaining
provider call in the package (OCI SCIM, B2, R2) in one pass; SDK
maintainers absorb wire-format drift, and `oci` ships a typed exception
hierarchy, closing the error-handling gap and the drift concern
together. Highest total effort: rewrites up to three provider modules
at once, and moves `ansible/tests/cloud_credentials/`'s mock boundary
for all of them at the same time.

### B — Adopt an SDK only where it's a clear improvement, leave the rest on `requests`

OCI's SCIM client (same package already a dependency — closes an
inconsistency where this repo uses `oci` for one auth model but not
the other) is close to an unambiguous win. B2's `b2sdk` is a genuine
but separate win with no shared blocker. R2's official SDK is a
thinner case: the surface used today (create/delete an account-scoped
token, look up permission-group IDs) is small and stable enough that
an SDK mostly saves JSON boilerplate, not drift risk — and R2's actual
weak point
([0014](../0014-r2-rotation-token-accepted-as-master-equivalent.md)'s
master-equivalent admin token) is unaffected by either client.

### C — Leave every client library alone, fix only the error-handling gap

Wrap each existing `requests` call site in a shared retry/exception
helper (timeout classification, bounded retry, one exception type
raised outward) without changing which HTTP client makes the call.
Smallest diff, but leaves OCI's already-present, already-unused `oci`
SCIM capability on the table, and does nothing for the JSON-shape drift
risk that motivated this in the first place.

## Decision

Option B:

1. OCI SCIM → `oci.identity_domains.IdentityDomainsClient`.
2. B2 → `b2sdk`.

R2 and OCI's classic-IAM bootstrap (`rotation_keys/oci_iam.py`) stay on
`requests` unless a later stage's findings change the call above.
`check_freshness.py`'s single Telegram `sendMessage` call has no SDK
candidate worth adding for one endpoint and stays as-is. `cache.py`'s
OpenBao/SSH client is a separate decision — see
[`openbao-client-hvac-paramiko-adoption.md`](openbao-client-hvac-paramiko-adoption.md).

## Assumptions

- **Claim:** `IdentityDomainsClient`'s `create_my_customer_secret_key`/
  `delete_my_customer_secret_key` reproduce the exact request/response
  shape [0016](../0016-oci-expiry-via-scim-not-self-tracked-cache-files.md)
  confirmed live against the raw SCIM API (`user.ocid` not `value`,
  `expiresOn` immutability, a genuinely populated `accessKey`/
  `secretKey` on create).
  **Breaks if wrong:** if the SDK's model classes don't expose those
  fields the same way, the OCI stage either needs SDK-specific
  workarounds or falls back to `requests` for that call, undermining
  the swap.
  **Checked by:** a spike creating and deleting one real customer
  secret key through the SDK against the actual tenancy, diffed against
  `leaf_keys/oci.py`'s current behavior.
- **Claim:** `b2sdk` exposes B2's exact capability set (bucket
  restriction rejection on rotation keys, `listAllBucketNames`,
  `readFiles` for `HeadObject`) without abstracting it behind an
  interface that hides which capability was actually granted.
  **Breaks if wrong:** if `b2sdk` wraps key creation behind a
  higher-level call that doesn't let this repo request the precise
  capability list `leaf_keys/b2.py` depends on, the hard-won findings in
  `cloud-credential-creation.md` get harder to keep verifying, not
  easier.
  **Checked by:** a spike creating one bucket-restricted key through
  `b2sdk`, confirming its returned capabilities match a key created the
  current way.
- **Claim:** R2's official SDK doesn't meaningfully reduce risk given
  how small and stable the surface used here is.
  **Breaks if wrong:** if Cloudflare's account-token API has changed
  more often than assumed, Option B's "not worth it" call on R2
  weakens.
  **Checked by:** not resolvable by reading docs now — revisit only if
  a future rotation run hits an actual breaking change on this
  specific endpoint.

## Consequences

- Every provider-specific quirk in `cloud-credential-creation.md` needs
  re-verifying against whichever SDK replaces its raw calls — each
  spike above exists because the semantics, not just the client, need
  confirming.
- `ansible/tests/cloud_credentials/`'s mock boundary moves per stage
  (from `requests` call sites to SDK client calls), rewritten
  module-by-module rather than in one pass.
- New dependency: `b2sdk`. `oci` needs no new dependency, just wider
  use of a package already pinned.
- This draft's stages are independent of
  [`openbao-client-hvac-paramiko-adoption.md`](openbao-client-hvac-paramiko-adoption.md)'s
  — neither blocks the other, since one is provider control-plane
  clients and the other is the Vault storage layer underneath them.
