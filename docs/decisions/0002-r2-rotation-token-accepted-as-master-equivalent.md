# 0002. Accept Cloudflare R2's cached rotation token as master-equivalent

**Status:** Accepted

## Context

B2 and OCI both let `create_rotation_keys.py` mint a narrower delegate
credential from the master one — scoped to creating/deleting keys,
holding no file/bucket-data capabilities itself. Cloudflare's tokens
API structurally can't do the same: it rejects granting `API Tokens
Write` to any token created via the API itself (`400 {"code": 1001,
"message": "sub-token is not allowed to have permissions to manage
other tokens"}`). There is no R2 equivalent of `create_rotation_keys
--provider r2`.

Cloudflare also has no policy-condition mechanism restricting *which*
permissions a delegated identity can grant (unlike OCI's `any
{request.permission='USER_SECRETKEY_ADD', ...}`). A cached R2 admin
token can therefore mint a token with any permission the account
holder has — DNS, Zones, Workers, Access, billing — not just
R2-scoped ones.

The remaining option was caching a token a human creates directly in
the Cloudflare Console (creation via API is what's blocked, not reuse
of a Console-created one). `r2_rotation_token()` does exactly that:
prompts once, caches to `_rotation-key-cloudflare-r2-token`, and every
later call — including `--rotate` — reads the cache instead of
re-prompting.

## Decision

Cache the R2 admin token as the de facto rotation credential, and
accept that it is master-equivalent for blast-radius purposes — unlike
B2's/OCI's genuinely narrower rotation keys.

## Consequences

If `_rotation-key-cloudflare-r2-token` is ever compromised, the blast
radius is the full Cloudflare account, not just R2. This is accepted
rather than worked around because: (a) the same token was already
being typed in from the same password-manager entry on every run, so
caching it changes convenience, not exposure to a new party; and (b) a
future secrets manager (see
[0001](0001-credential-caching-stage-1-before-secrets-manager.md))
narrows who/what can reach the cached token, not what it can do once
reached — R2 is the one provider that gap won't close even after that
migration.

The R2 *leaf* tokens (used by `cloud_sync`/restore-discovery day to
day) are unaffected: they stay properly bucket-scoped and never hold
`API Tokens Write`, so they carry none of this risk. `cloud_sync`'s own
`rclone copy`-only design (never `sync`) is what actually prevents an
on-prem compromise from deleting R2 objects — see
[`disaster-recovery.md`](../disaster-recovery.md)'s Threat model. R2's
defense-in-depth is at the leaf-token/`copy`-vs-`sync` level, not IAM
narrowing at the rotation-token level.

See [`cloud-credential-creation.md`](../cloud-credential-creation.md#cloudflare-r2--rotation-key-exists-now-but-its-not-scoped-like-the-other-two)
for the R2 master-token setup steps this credential depends on.
