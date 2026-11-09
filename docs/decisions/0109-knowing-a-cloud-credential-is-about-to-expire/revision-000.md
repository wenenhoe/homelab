---
id: ADR-0109
revision: 0
type: adr
title: Knowing a cloud credential is about to expire
short: Cloud credential expiry
solution: Native expiry set at creation where a provider has one, a self-tracked timestamp where it has none, and a weekly check that alerts before the window ends
summary: Every cloud leaf credential and rotation key expires, something notices before it does, and OCI keys are minted and dated through the Identity Domains API because the classic API has no expiry field.
topic: cloud-credentials
status: accepted
related: [ADR-0023, ADR-0110]
former_ids: [ADR-0015, ADR-0016]
---

# 0109. Knowing a cloud credential is about to expire

## Problem

None of the leaf credentials or rotation keys that `cloud_credentials` creates used to expire.
A credential that never expires is never forgotten, but it is also never replaced, and a leak
stays useful for as long as nobody notices it. What has to be true: every leaf credential and
every rotation key or token has a window, the window can be read back, and something tells the
maintainer well before it ends, because an expired rotation credential stops routine rotation.

## Context

Providers differ in whether an expiry can be set at creation and read back later.

- **B2** accepts `validDurationInSeconds` on `b2_create_key` (a positive integer under 1000
  days). The response carries `expirationTimestamp`, and `b2_list_keys` reads it later.
- **R2** accepts an optional `expires_on` on `POST /accounts/{account_id}/tokens`, the call
  `r2_create_leaf_token` already makes, and `GET /accounts/{account_id}/tokens/{token_id}` reads
  it back without the token itself. The rotation admin token is a Console token a person creates
  ([ADR 0110](../0110-the-r2-admin-token-as-the-rotation-credential/revision-000.md)), so it
  carries an expiry set by hand, read back the same way. The specific endpoint is described in
  `cloud-credentials/expiry.md` and is not restated here.
- **OCI's classic Identity API** has no expiry concept: `CreateCustomerSecretKeyDetails` has one
  attribute, `display_name`. Identity Domains' `CustomerSecretKey` resource does have `expiresOn`,
  but it is reachable only through the domain's SCIM endpoint, which rejects the rotation
  identity's request-signing outright with a 401. SCIM authenticates with OAuth2 client
  credentials from a registered Confidential Application, a different auth model from the signing
  used everywhere else in the repository. That integration was built and confirmed live against
  the tenancy:
  - A Confidential Application with OAuth2 client credentials and the **User Administrator**
    domain app role can call `POST /admin/v1/CustomerSecretKeys`.
  - `expiresOn` is immutable, settable at create, and round-trips as the same instant. OCI echoes
    it back with explicit milliseconds, so a string comparison reads a false mismatch where an
    instant comparison does not.
  - The `user` sub-object takes the user's OCID in its `ocid` field. `value` is a shorter,
    unrelated 40-character id and rejects an OCID.
  - `accessKey` and `secretKey` come back populated on create, so SCIM creation produces a usable
    key pair and not metadata bolted on to a key made through the classic API.
  - The Confidential Application's own client secret has no native expiry, and regenerating it
    through `AppClientSecretRegenerator` is a hard cutover: one active secret per application, the
    old one invalid at once.

A check has to run unattended and alert on a credential past its window. `cloud_credentials` is
not an Ansible role and deploys to no managed host. Its state lives under
`ansible/files/secrets/` on the `controller` host only, the operator's own machine, so that is
the one place a check can read it without moving secret material or timestamps anywhere new.

## Decision

- **B2 and R2 set native expiry at creation,** for leaf credentials and for rotation keys and
  tokens alike. No cache file tracks either.
- **OCI leaf keys are created through the Identity Domains SCIM API** with a Confidential
  Application's OAuth2 client credentials, and `expiresOn` is set in the same call. The classic
  `CreateCustomerSecretKeyDetails` call is not used for keys, and its code path
  (`oci_ensure_rotation_identity`, `_verify_rotation_key` and the RSA-keypair generation) is
  removed, not left beside the new one. `audit.py --provider oci` also reads through SCIM
  (`GET /admin/v1/CustomerSecretKeys?filter=user.ocid eq "..."`).
- **The OCI rotation credential is the Confidential Application's client ID and secret,** which
  replace the OCID and PEM keypair. It has no native expiry, so a companion `<credential>-created-at`
  timestamp is self-tracked beside it.
- **Classic OCI IAM is still used only for leaf-identity bootstrapping**
  (`oci_ensure_leaf_identity`), which `~/.oci/config` still serves.
- **`check_freshness.py` (renamed: `check_credential_expiry.py`) classifies each credential** as fresh, expiring within
  `expiry.WARNING_DAYS` (30 days), expiring within `expiry.URGENT_DAYS` (14 days), past its window,
  or check-failed. It queries B2 and R2 live and reads OCI's self-tracked timestamp. Only a genuine
  check failure fails the run's exit code; every other non-fresh result posts a Telegram alert to
  the `Backups` topic. There are two warning grades so the reminder escalates as the deadline nears
  and does not repeat flat every run. A plain fresh or past-window split was dropped: B2 and R2
  enforce expiry server-side, so "past its window" there means `cloud_sync` is already broken.
- **The check runs as a systemd user timer on `controller`,** installed by hand once from
  `tools/cloud_credentials/systemd/`, not as an Ansible role or a unit on a managed host.
- **Every credential has a 90-day window,** enforced by the provider for B2 and R2 and by the check
  alone for the OCI rotation credential.

## Alternatives considered

- **Track every expiry in cache files.** Needed only for OCI's rotation credential; B2 and R2 can be
  asked.
- **Keep the OCI classic API and self-track its leaf keys.** Leaf keys could then not expire at the
  provider, which is the gap this closes.
- **Run the check on a managed host.** It would need read access to the credential state, a
  materially different security posture.

## Consequences

- OCI leaf keys join B2 and R2 with no self-tracked file. The rotation credential still has one,
  so the gap narrows and does not close.
- An OCI credential past its self-tracked window keeps working at the provider until someone
  rotates it. For OCI's rotation credential the check is advisory, not enforcement.
- An expired rotation credential breaks routine leaf rotation until a person re-runs
  `create_rotation_keys` (B2, OCI) or pastes a new Console token (R2).
- Regenerating the Confidential Application's client secret has no verify-before-revoke.
  `rotate_oci_rotation_key` caches the new secret as soon as it is returned, before verifying it,
  since the old one is gone either way.
- A new long-lived credential replaces the old OCI rotation keypair, which is gone.
- The check depends on `controller` being on often enough for a weekly `Persistent=true` timer to
  catch up. On a machine that is off for a long stretch this is a real gap, and there is no fallback
  host without giving some managed host read access to the credential state.
- A missing `telegram-token` or `telegram-chat-id` downgrades an alert to a journal line without
  failing the run.
- OCI's open gap, that no confirmed policy condition scopes `manage users` to one resource, is
  unrelated to this record.

Setup and verification steps are in
[`cloud-credentials/expiry.md`](../../topics/secrets/cloud-credentials/expiry.md#credential-expiry).

## Invariants

- Every cloud leaf credential and rotation key or token has an expiry that can be read back, from
  the provider or from a timestamp written when the credential was created.
- A credential within its warning window raises an alert; only a failed check fails the run.
- OCI keys are created and dated through the Identity Domains API, never the classic key call.
- No managed host reads the credential state to run the check.

## Non-goals

- What the R2 admin token can do once held, and where it is kept
  ([ADR 0110](../0110-the-r2-admin-token-as-the-rotation-credential/revision-000.md)).
- When credentials are rotated and where their state is stored
  ([ADR 0023](../0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md)).
- Enforcing expiry for OCI's rotation credential at the provider, which OCI does not offer.
- Running the check unattended on an always-on host.

## Reconsideration triggers

- OCI's classic Identity API gains an expiry field, or the Confidential Application's client secret
  gains one or allows overlapping secrets.
- A provider changes how expiry is set or read back.
- `controller` proves too unreliable to run the weekly timer, which would justify a dedicated host
  and a design for its read access.
