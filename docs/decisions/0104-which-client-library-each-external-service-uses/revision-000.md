---
id: ADR-0104
revision: 0
type: adr
title: Which client library each external service uses
short: Python client libraries
solution: "Official SDKs for OCI SCIM and B2, hvac and paramiko for OpenBao, and rclone for S3-compatible storage; raw requests for R2 and OCI classic IAM"
summary: Which client library the repo's Python uses for each cloud provider, OpenBao and S3-compatible storage, so each client's behaviour is known and the offsite-copy guarantees hold.
topic: cloud-credentials
status: accepted
related: [ADR-0010, ADR-0016, ADR-0067]
former_ids: [ADR-0029, ADR-0030, ADR-0046]
---

# 0104. Which client library each external service uses

## Problem

The repo's Python calls cloud-provider control planes (B2, R2, OCI), OpenBao
and S3-compatible object storage. Each call had been hand-rolled over `requests`
or shelled out to `ssh`, with no retry, inconsistent exception handling and the
same defect (an SSH call with no timeout) fixed in one copy and left in another.
Each service needs one client whose behaviour is known, chosen without
weakening the guarantees the backup design rests on.

## Context

- **Cloud-provider control planes.** Every module under `tools/cloud_credentials/`
  called B2, R2 and OCI over `requests`. The `oci` package was already a pinned
  dependency, used for classic-IAM bootstrap, but the OCI SCIM flow
  reimplemented its OAuth2 exchange and calls instead of using
  `oci.identity_domains.IdentityDomainsClient`. Official clients exist: `oci`,
  `b2sdk` for B2 key management, and Cloudflare's SDK for R2 account tokens.
- **OpenBao.** The credentials library and the bootstrap script each hand-rolled
  an AppRole login and KV v2 read and write over `requests`, and each fetched
  step-ca's root certificate through an `ssh ... docker exec` subprocess with no
  timeout. The audit script and the standing R2 read watcher repeated the same
  surface. The watcher logs in once at startup to fetch alerting secrets and
  never presents that token again, so token renewal does not apply to it.
- **S3-compatible storage.** `rclone` runs at five call sites. Three are bash
  scripts running `rclone` in a pinned container for bulk copy. Two are Python
  (`cloud_credentials/verify.py` and `restore_all.py`) that shell out for single
  objects. `cloud_sync`'s `rclone copy` is the control that keeps a compromised
  on-prem host from touching the offsite copy, because `copy` never overwrites or
  deletes ([ADR 0010](../0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md)).
  `verify_leaf_via_rclone` proves a freshly minted leaf key works over the path
  production uses before the old key is revoked, which exercises permissions a
  check without rclone's HEAD-before-copy would miss. `restore_all.py` never holds
  S3 credentials in its own process.
- **Measured against B2, R2 and OCI** with rclone 1.75.0 and boto3 1.43.108:
  rclone lists with the v1 call and writes with HEAD, PUT, HEAD, where boto3
  sends a v2 listing and a single PUT. boto3 needed different settings per
  provider: OCI answers the default checksum PUT with `501`, B2 closed the
  connection on a PUT carrying `Expect: 100-continue` under
  `request_checksum_calculation="when_required"` and returned `400` once `Expect`
  was removed, and only the default checksum mode with `Expect` removed succeeded;
  R2 accepted every variant tried.

## Decision

**Cloud-provider control planes** adopt an SDK only where it is a clear
improvement, and leave the rest on `requests`:

1. OCI SCIM goes through `oci.identity_domains.IdentityDomainsClient`.
2. B2 goes through `b2sdk`.

R2's account-token calls and OCI's classic-IAM bootstrap
(`rotation_keys/oci_iam.py`) stay on `requests`: the R2 surface is small and
stable, so an SDK would save boilerplate and no drift risk. The single Telegram
`sendMessage` call in `check_freshness.py` stays as it is. The one SCIM call the
SDK does not cover, regenerating an application client secret, stays on raw
`requests`.

**OpenBao.** Every internal Python client that talks to OpenBao directly uses
`hvac` for the Vault client and, where an SSH hop is needed to fetch step-ca's
root certificate, `paramiko` in place of a `subprocess` call to `ssh`. `paramiko`
loads the system host keys and uses `AutoAddPolicy`, which reproduces
trust-on-first-use and fails closed on a changed key. Every SSH call has a
bounded timeout. `hvac`'s `raise_on_deleted_version` is pinned to `True` in every
read call. How the clients share code is a matter of where tooling lives, not of
which library they use.

**S3-compatible storage.** `rclone` remains the client at every call site, Python
and bash. `verify.py` and `restore_all.py` stay on it, and `boto3` is not added to
`pyproject.toml`. Two reasons decide it. Verification must follow production's
client, since a key could pass a boto3 check and still fail under rclone. And
rclone needs one configuration for all three providers, recorded once in
[`rotation.md`](../../topics/secrets/cloud-credentials/rotation.md), where boto3
would add a per-provider checksum setting and, for B2, a hook that removes a header
botocore adds by default.

## Alternatives considered

- **Swap every raw call for its SDK at once.** The largest rewrite and moves the
  mock boundary for every provider together; R2's SDK adds little.
- **Leave every client alone and add a shared retry helper.** Smallest change,
  but leaves the SDK already present unused and does nothing for wire-format drift.
- **boto3 for both Python S3 sites.** Gives up `restore_all.py`'s property that S3
  credentials never enter the Python process, and carries the per-provider settings.
- **boto3 for `verify.py` only.** Loses the same-path property and still needs the
  per-provider settings.
- **Third-party rclone wrappers.** They shell out to the same CLI, so they remove no
  wire-format drift, and they are one maintainer's project in a credential path.
- **rclone's Remote Control API.** Needs a standing daemon and an auth token for
  scripts that run a few times a quarter.

## Consequences

- `IdentityDomainsClient` has no bearer-token mode, so SCIM uses an auth subclass
  that injects the OAuth2 token and inert placeholder config values.
- Mocks of an SDK object use `spec=` the real class, so a wrong attribute name
  fails the unit tests, not only a live run.
- `b2sdk` is a new dependency; `oci` and `hvac` needed none.
- Swapping rclone for boto3 plus `hvac` would not remove a secret from disk, only
  change which one, which is the problem of
  [ADR 0047](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md)
  one level up.
- `verify.py` keeps its status-string retry gate (`StatusCode: 401` or `403` in
  rclone's stderr) and its timeout handling.
- Behaviour is described in [`rotation.md`](../../topics/secrets/cloud-credentials/rotation.md),
  [`scoping.md`](../../topics/secrets/cloud-credentials/scoping.md) and
  [`creation.md`](../../topics/secrets/cloud-credentials/creation.md).

## Non-goals

- Whether the three bash scripts become Python wrappers around the same `rclone`
  binary. That keeps `rclone copy`'s semantics but changes the deployment shape (a
  container with no Python interpreter today), so it needs its own record.
- Where the shared OpenBao client code lives.

## Reconsideration triggers

- `cloud_sync` or `restore_all.py` stops using rclone, so verification should follow
  the new client.
- A provider's S3-compatible API starts requiring a request shape rclone cannot
  produce.
- A rotation run hits a breaking change on the R2 account-token endpoint.
