---
id: ADR-0029
title: "Adopt official SDKs in cloud_credentials selectively, not as a blanket swap"
type: adr
status: accepted
---

# 0029. Adopt official SDKs in cloud_credentials selectively, not as a blanket swap

**Status:** Accepted

## Context

Every module under `ansible/cloud_credentials/` talked to B2/R2/OCI
entirely over hand-rolled `requests` calls. The `oci` package was
already a pinned dependency (`oci.signer.Signer`,
`oci.config.from_file` — `rotation_keys/oci_iam.py`'s classic-IAM
bootstrap, per `cloud-credential-creation.md`), but the OCI SCIM
leaf/rotation flow (`leaf_keys/oci.py`, `rotation_keys/oci_bootstrap.py`,
`rotation_keys/oci_scim.py`, added by
[0016](0016-oci-expiry-via-scim-not-self-tracked-cache-files.md))
reimplemented the OAuth2 client-credentials exchange and every SCIM
call over raw `requests` instead of the same package's
`oci.identity_domains.IdentityDomainsClient`.

No retry/backoff existed for any of these calls (`verify.py`'s
`rclone` retry logic is a separate matter — see
[`rclone-boto3-scope-not-blanket-swap.md`](drafts/rclone-boto3-scope-not-blanket-swap.md)).
Exception handling was also inconsistent: most `create_*`/`rotate_*`
call sites caught `requests.HTTPError` (raised only by
`.raise_for_status()`); `check_freshness.py` caught the broader
`requests.RequestException`.

Officially maintained clients exist for these targets: the `oci`
package already in use (its `identity_domains.IdentityDomainsClient` +
`CustomerSecretKey`/`CustomerSecretKeyUser` models cover exactly the
SCIM flow above), `Backblaze/b2sdk` for B2 key management, and
Cloudflare's official Python SDK for R2's account API-token calls.

`cache.py`'s OpenBao KV v2 client (`hvac`) and its `_fetch_root_cert`
SSH call (`paramiko`) are **not** decided here — the same gap exists
independently in `bootstrap_secrets.py`, `audit_secrets.py`, and
`docker/openbao/watcher/r2_read_watcher.py`, so that question is scoped
across all four in
[`0030-openbao-hvac-paramiko-clients.md`](0030-openbao-hvac-paramiko-clients.md)
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
([0014](0014-r2-rotation-token-accepted-as-master-equivalent.md)'s
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
`requests`. `check_freshness.py`'s single Telegram `sendMessage` call
has no SDK candidate worth adding for one endpoint and stays as-is.
`cache.py`'s OpenBao/SSH client is a separate decision — see
[`0030-openbao-hvac-paramiko-clients.md`](0030-openbao-hvac-paramiko-clients.md).

Both migrations are built and confirmed live:

- OCI SCIM leaf/rotation (`leaf_keys/oci.py`,
  `rotation_keys/oci_bootstrap.py`'s Apps-by-displayName lookup,
  `rotation_keys/oci_scim.py`) now goes through
  `IdentityDomainsClient`. A live spike creating and deleting one real
  customer secret key confirmed `create_customer_secret_key`/
  `delete_customer_secret_key` reproduce the field shape
  [0016](0016-oci-expiry-via-scim-not-self-tracked-cache-files.md)
  established (`user.ocid`, populated `access_key`/`secret_key`, a
  plausible `expires_on`).
- B2 (`leaf_keys/b2.py`, `rotation_keys/b2.py`, and the B2 call sites in
  `check_freshness.py`/`create_snapshot_readonly_keys.py`/
  `create_snapshot_write_keys.py`) now goes through `b2sdk`'s `B2Api`.
  A live spike confirmed `create_key(capabilities=...)` returns the
  exact, unwrapped capability list requested.

## Consequences

- `IdentityDomainsClient` has no built-in bearer-token auth mode — its
  `signer` only implements OCI's own API-key Signature V1. The
  implementation adds a `requests.auth.AuthBase` subclass
  (`oci_scim.py`'s `_BearerTokenSigner`) that injects the SCIM OAuth2
  token instead, plus well-formed-but-inert placeholder config values
  to satisfy `IdentityDomainsClient.__init__`'s config validation
  (which runs regardless of which signer is used) — confirmed working
  end to end by the live spike above.
- There is no SDK method for `AppClientSecretRegenerator` at all.
  `rotation_keys/oci_bootstrap.py`'s `rotate_oci_rotation_key` stays on
  raw `requests` for that one call — a hard SDK-coverage gap, not a
  choice this decision made.
- `FullApplicationKey.__init__` takes `application_key_id` as a
  constructor parameter but stores it as `self.id_`, not
  `self.application_key_id` — a mismatch static inspection of the
  constructor signature missed, caught only by a live spike
  (`AttributeError` on the first attempt). Every B2 call site that
  reads a newly created key's id uses `.id_` now (see
  `leaf_keys/b2.py`'s `b2_create_leaf_key`). The unit tests hadn't
  caught it either, since they mocked the return value as a bare
  `MagicMock(application_key_id=...)`, which accepts any attribute
  name silently — every such mock is now `spec=FullApplicationKey`
  instead, so a future name mismatch fails the unit tests too, not
  just a live run.
- R2's official SDK was judged not worth adopting given how small and
  stable the surface used here is (create/delete an account-scoped
  token, look up permission-group IDs) — not independently verified
  against a real breaking change, since there wasn't one to check
  against. If a future rotation run ever hits a genuine breaking
  change on this specific Cloudflare endpoint, that's the trigger to
  revisit this call, not a scheduled recheck.
- Every provider-specific quirk in `cloud-credential-creation.md`
  needed re-verifying against whichever SDK replaced its raw calls —
  confirmed live for both OCI and B2, not just read from SDK docs.
- `ansible/tests/cloud_credentials/`'s mock boundary moved per
  provider (from `requests` call sites to SDK client calls), rewritten
  module-by-module rather than in one pass.
- New dependency: `b2sdk`. `oci` needed no new dependency, just wider
  use of a package already pinned.
- This decision is independent of
  [`0030-openbao-hvac-paramiko-clients.md`](0030-openbao-hvac-paramiko-clients.md)'s
  — neither blocks the other, since one is provider control-plane
  clients and the other is the Vault storage layer underneath them.
