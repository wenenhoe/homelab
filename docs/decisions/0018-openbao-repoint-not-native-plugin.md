# 0018. Repoint existing credential scripts at OpenBao KV v2, defer a native plugin

**Status:** Proposed

## Context

`ansible/cloud_credentials/` already encodes real, hard-won
per-provider logic that has nothing to do with where the result is
stored: B2's `validDurationInSeconds` and `readFiles`-for-`HeadObject`
requirement, OCI's Identity Domains SCIM/Confidential-Application model
([0016](0016-oci-expiry-via-scim-not-self-tracked-cache-files.md)), and
R2's hard no-sub-token-delegation ceiling
([0002](0002-r2-rotation-token-accepted-as-master-equivalent.md)).
Moving to OpenBao means deciding what changes: only the storage target,
or the mechanism doing the minting/rotating too.

OpenBao ships native automated rotation only for specific first-party
engines (databases, AWS IAM, etc.) — nothing for R2/B2/OCI object
storage. A native OpenBao secrets-engine plugin (Go) could add real
lease-based rotation for these providers, but it would mean
reimplementing every provider quirk above inside a compiled plugin
instead of the Python this repo already tests
(`ansible/tests/cloud_credentials/`), for a homelab with one operator
and a rotation cadence (see Decision, below) that a scheduled script
already meets.

A second open question sits underneath this one: OpenBao's KV v2 engine
stores arbitrary data, not leased dynamic secrets — its own docs are
explicit that the KV backend does not issue leases for what it stores,
though a read may still echo back a lease duration. So even a native
plugin wouldn't get free expiry tracking for KV-stored values; only a
genuine dynamic-secrets engine would, and building one is exactly the
Path B work this ADR is deferring.

## Decision

**Path A:** keep every existing Python provider module as-is —
`leaf_keys/{b2,oci,r2}.py`, `rotation_keys/{b2,oci_bootstrap,oci_iam}.py`,
and the shared `cache.py`/`verify.py`/`expiry.py`/`check_freshness.py` —
and repoint only their storage target from
`ansible/files/secrets/`/local cache files to OpenBao's KV v2 API.
Rotation and expiry logic don't get rebuilt, only where they persist
state.

**Path B** (a real OpenBao secrets-engine plugin for native
lease-based rotation) is deferred, not rejected. Revisit only if Path
A's script-based approach becomes a maintenance burden — e.g. if
`check_freshness.py`'s external-timer pattern proves unreliable in
practice, or a provider adds a native dynamic-secrets-compatible API.

Because KV v2 confirmed above has no lease/expiry mechanism to lean on,
`check_freshness.py` keeps its current shape post-migration: still an
external check reading expiry data and alerting via Telegram, just
reading from Vault's KV v2 (native fields where B2/R2/OCI SCIM already
provide them, `custom_metadata` for OCI's self-tracked rotation-secret
timestamp) instead of `ansible/files/secrets/`.

Vault as the store, plus a persistent host that can reach it
programmatically ([0020](0020-pull-based-cd-agent-not-self-hosted-github-runner.md)),
removes the last reason rotation stayed human-attended. Rotation moves
to a schedule: **leaf credentials** (all 6, across B2/R2/OCI) rotate
every 30 days — a third of their 90-day expiry window
([0015](0015-credential-expiry-native-where-possible-self-tracked-where-not.md)),
so a leaf credential is never within `check_freshness.py`'s own
WARNING threshold under normal operation; its alerting becomes a
safety net for a missed run, not the primary trigger. **Rotation/master
credentials** rotate every 90 days, matching the existing expiry
window rather than tightening it further — kept at parity because
master-tier rotation already carries more risk per credential than a
leaf rotation (OCI's Confidential Application secret has no
verify-before-revoke at all, per
[0016](0016-oci-expiry-via-scim-not-self-tracked-cache-files.md)), and
a shorter cycle would multiply that risk without a clear benefit. For
B2 and OCI, `create_rotation_keys.py --rotate {write,read,both}`'s
existing mint-verify-revoke flow runs unattended on this schedule; R2
is a structural exception — see
[0019](0019-r2-admin-token-into-openbao.md) for why its master token
can't be minted the same way.

Both schedules, and `check_freshness.py` itself, are triggered the
same way as `cd_agent`'s deploy and maintenance jobs
([0020](0020-pull-based-cd-agent-not-self-hosted-github-runner.md)) —
run on that host, not on `controller`. `controller` (the operator's
own machine) no longer runs any part of the credential lifecycle
unattended once this lands; its remaining role is one-time bootstrap
actions only, consistent with it never being a `managed_hosts` member.

## Consequences

- Every provider-specific quirk currently hard-won in
  `ansible/cloud_credentials/` carries forward unchanged; the
  migration roadmap's cloud-credential migration stage is a
  storage-layer swap, not a rewrite.
- No new compiled-plugin toolchain (Go, plugin registration, OpenBao's
  plugin catalog) enters this repo for this migration.
- Rotation and expiry remain script-driven and schedule-based, not
  lease-driven — the same operational model as today, just with Vault
  as the store instead of flat files. A credential past its window
  still keeps working provider-side until a human or automation
  re-runs rotation, exactly as `check_freshness.py`'s advisory-only
  status already describes.
- If Path B is ever picked up, it starts from the same per-provider
  logic this ADR preserves rather than from scratch.
- `cd_agent` now runs two categories of unattended, prod-touching work
  under one host: `deploy.yaml`/`maintenance.yaml`
  ([0020](0020-pull-based-cd-agent-not-self-hosted-github-runner.md))
  and credential rotation/freshness. See
  [0022](0022-approle-policy-structure-two-eras.md) for why these are
  two separate AppRoles/policies rather than one shared identity.
- OCI's Confidential Application secret regenerating automatically
  every 90 days with no rollback (per
  [0016](0016-oci-expiry-via-scim-not-self-tracked-cache-files.md))
  needs a tested failure path before this goes live — verified in a
  restore drill (during the backup/restore proving stage, or again at
  the later cutover stage), not assumed safe by analogy to B2/R2.
- A 30-day leaf cadence triples the previous check-in frequency against
  each provider's API. Whether any provider rate-limits credential
  creation at that frequency isn't confirmed either way — a build
  question for the secrets-role or cloud-credential migration stages,
  not guessed here.
