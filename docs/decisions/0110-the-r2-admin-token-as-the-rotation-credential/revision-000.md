---
id: ADR-0110
revision: 0
type: adr
title: The R2 admin token as the rotation credential
short: R2 admin token custody
solution: Cache the human-made R2 admin token as the rotation credential, accepted as master-equivalent, kept in OpenBao under one path with an alert on every read
summary: Cloudflare cannot mint a narrower delegate for R2's rotation credential, so its blast radius is accepted, where it lives is fixed, and every read of it is alerted.
topic: cloud-credentials
status: accepted
related: [ADR-0010, ADR-0020, ADR-0023, ADR-0026, ADR-0109]
former_ids: [ADR-0014, ADR-0024]
---

# 0110. The R2 admin token as the rotation credential

## Problem

B2 and OCI let the repository mint a narrow delegate from the master credential, so the rotation
key can create and delete keys and nothing else. Cloudflare does not. What has to be true: R2 has a
rotation credential anyway, the exposure that follows from its breadth is accepted knowingly and
contained where it can be, and its storage and its reads are as controlled as for the credentials
that can be narrowed.

## Context

Cloudflare's tokens API rejects granting `API Tokens Write` to any token created through the API
(`400 {"code": 1001, "message": "sub-token is not allowed to have permissions to manage other
tokens"}`), and it has no policy condition that limits which permissions a delegated identity can
grant, unlike OCI's `any {request.permission='USER_SECRETKEY_ADD', ...}`. A cached R2 admin token
can therefore mint a token with any permission the account holder has: DNS, Zones, Workers, Access
and billing, not only R2.

`create_rotation_keys --provider r2` therefore never mints anything. It caches, or with `--rotate`
re-caches, a token a person creates directly in the Console. Creation through the API is what is
blocked, not reuse of a Console-made token. `r2_rotation_token()` and
`cache_r2_rotation_token()` / `rotate_r2_rotation_token()` share one prompt: the token is cached on
first use, and every later call, including `create_leaf_keys.py --rotate`, reads the cache unless
rotation is run explicitly.

Moving every other credential into OpenBao
([ADR 0023](../0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md)) would
leave R2's token as the one credential in `ansible/files/secrets/`, and whatever runs rotation
unattended would need filesystem access to that flat-file cache for this one provider. Moving it was
worth doing only once an automated consumer justified the tighter access control, and not for the
sake of the storage location.

**Threat model.** The asset is the token and, through it, the Cloudflare account. The path is a read
of the cached token by anything with access to wherever it is kept. The same token was already typed
in from a password manager on every run before it was cached, so caching changes convenience, not
the set of parties exposed.

## Decision

- **Cache the R2 admin token as the de facto rotation credential,** and accept that it is
  master-equivalent for blast-radius purposes, unlike B2's and OCI's narrower rotation keys.
- **Keep it in OpenBao KV v2** alongside the other credentials, scoped to one Vault path, so no
  flat-file exception remains.
- **Alert on every read of that path,** not only on its expiry. The source is Vault's audit log, an
  event-triggered alert and not a poll like `check_freshness.py` (renamed: `check_credential_expiry.py`), because a read alert has to fire
  per access ([ADR 0026](../0026-detecting-reads-of-high-value-secrets/revision-000.md)). Today the
  path is reachable under `controller`'s single broad policy
  ([ADR 0020](../0020-automation-identity-and-access-scope/revision-000.md)); a dedicated
  rotation-only identity is future work, once one exists.
- **A human renews it.** `check_freshness.py` checks whether the cached token's `expires_on`
  ([ADR 0109](../0109-knowing-a-cloud-credential-is-about-to-expire/revision-000.md)) is inside the
  rotation window and, if so, alerts that a person must create a new Console token. The only
  automated part is caching the pasted token into Vault and verifying it authenticates.

## Alternatives considered

- **Mint a narrower delegate.** Cloudflare's API refuses it.
- **Leave the token in a flat-file cache.** It would be the one exception left in the old storage
  and would give an unattended consumer filesystem access for one provider.
- **Wait for a secrets manager to narrow it.** A secrets manager narrows who can reach the token,
  not what it can do once reached; R2 is the one provider that gap does not close.

## Consequences

- If the token is compromised, the blast radius is the whole Cloudflare account, not only R2. This
  is accepted and not worked around, because moving it changes who and what can reach it and never
  what it can do.
- R2's leaf tokens, used by `cloud_sync` and restore discovery, are unaffected: they stay
  bucket-scoped and never hold `API Tokens Write`. `cloud_sync` using `rclone copy` and never `sync`
  is what stops an on-site compromise deleting R2 objects, as
  [`backup-threat-model.md`](../../topics/disaster-recovery/backup-threat-model.md) describes. R2's
  defence in depth is at the leaf-token and `copy`-versus-`sync` level, not IAM narrowing.
- R2's 90-day cycle cannot be fully unattended the way B2's and OCI's can; a person creating a
  Console token every 90 days is a hard requirement.
- The per-read alert is new work, since no consumer in `tools/cloud_credentials/` alerted on access
  rather than on expiry.

R2 master-token setup steps are in
[`cloud-credentials/scoping.md`](../../topics/secrets/cloud-credentials/scoping.md#cloudflare-r2--rotation-key-exists-now-but-its-not-scoped-like-the-other-two).

## Invariants

- The R2 rotation credential is a token a person created in the Console; no code path mints it.
- It is kept in OpenBao under one path and nowhere in a flat-file cache.
- Every read of that path raises an alert.
- R2 leaf tokens are bucket-scoped and never hold `API Tokens Write`.

## Non-goals

- Narrowing the token, which Cloudflare does not allow.
- Expiry dating and the freshness check in general
  ([ADR 0109](../0109-knowing-a-cloud-credential-is-about-to-expire/revision-000.md)).
- How rotation is scheduled and how credential code stores its output
  ([ADR 0023](../0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md)).
- A dedicated rotation-only identity for reading the path.

## Reconsideration triggers

- Cloudflare allows an API-created token to hold `API Tokens Write`, or adds a way to restrict which
  permissions a delegated token may grant.
- A dedicated rotation identity exists and can be given this one path.
- An automated consumer of the token makes the per-read alert too noisy to act on.
