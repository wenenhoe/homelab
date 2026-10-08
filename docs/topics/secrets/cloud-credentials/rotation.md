# Cloud Credential Rotation — R2/B2/OCI

How the leaf and rotation credentials are rotated, per provider: the `--rotate` flow and its verification, the `rclone` settings that verification depends on, and rotating the rotation credential itself. Creation is in [`creation.md`](creation.md); what each credential is scoped to is in [`scoping.md`](scoping.md).

## Rotation

### Leftover pre-Vault cache files

`openbao_utils/audit.py --local` flags anything under
`ansible/files/secrets/` that doesn't match current config, whatever its vintage. It has no
visibility into Console-side IAM objects, so the cleanup from the OCI SCIM migration
([ADR 0016 (OCI credential creation)](../../../decisions/0016-oci-credential-creation-and-expiry/revision-000.md)) stays manual if you
never did it: delete the unused `homelab-key-rotation` identity — its API signing key first, then the policy,
then the group membership, then the user itself.

### Rotating leaf keys

`--rotate {write,read,both}` works for all three providers:

```sh
cd tools
python3 -m cloud_credentials.create_leaf_keys --provider b2 --rotate write
python3 -m cloud_credentials.create_leaf_keys --provider oci --rotate both
python3 -m cloud_credentials.create_leaf_keys --provider r2 --rotate read
```

**All six leaves in one run:**

```sh
cd tools
python3 -m cloud_credentials.rotate_leaf_keys
```

It runs `--rotate both` for B2, then OCI, then R2, and takes no arguments. A provider that reports a failed verification, exits or raises does not stop the ones after it, because each provider's keys rotate on their own and one failing leaves the others still due. It names the failed providers on stderr and exits 1 if there were any. It asks for nothing itself, but R2's fallback prompt for its admin token cannot be answered without a terminal, so that provider fails unless the token is already cached (`create_rotation_keys --provider r2`, below).

Order of operations, per leaf: create a new provider-side key → verify
it actually works over the same rclone S3-compatible path
cloud_sync/restore-discovery use in production (a `ListObjects` listing
for the read leaf — rclone lists with the v1 call on B2, R2, and OCI —
and HeadObject, PutObject, HeadObject for the write leaf — see
`verify_leaf_via_rclone` in `cloud_credentials/verify.py`) → only then
revoke the old key and overwrite its cache entry. **If verification
fails, both keys are left live and the cache is left untouched** — the
old key keeps working, the new (unverified, unrevoked) key is reported
so it can be investigated or deleted by hand; nothing is silently
rolled back or retried. Each leaf is independent, so `--rotate write`
never touches the read leaf's key or cache.

### Verification

**Verification retries through each provider's key-propagation
window.** A brand-new leaf credential isn't always immediately usable by
the provider's S3-compat API — the same request with an
already-propagated key succeeds, a just-created one fails until it
propagates. Each provider surfaces this differently and gives no way
to distinguish it from a genuine policy denial, so the retry gate
matches broadly on HTTP status alone (`StatusCode: 403` or
`StatusCode: 401`) rather than specific error text — accepted
deliberately: a real policy problem now takes the full retry window
to surface as a failure instead of failing instantly,
but the alternative (no retry) means every manual re-run of a failed
`--rotate` mints and orphans a fresh provider-side key while waiting
out propagation by hand. Propagation windows differ a lot by provider (OCI the longest, R2 the
shortest), all inside the current ceiling. Widen
`_run_rclone_with_retry`'s `retries`/`delay` if a real rotation ever
exhausts it. A hung rclone call (past its `--timeout`) is not a propagation
denial: it fails verification like any other non-retryable error
instead of being retried through the window. A first success doesn't mean the key
has reached every node: on OCI, later requests from fresh connections
were still denied with 403 for a minute or more after the first
successful call, so a passing verification means the key works now, not
that propagation has finished.

**Verification stays on rclone, not an SDK client**, because it has to
follow production's request sequence. boto3 sends a different one (no
HEAD around the write, a v2 listing) and needs different settings per
provider, so a key could pass a boto3 check and still fail under rclone.
The comparison is in
[ADR 0046 (S3 client)](../../../decisions/0046-python-client-for-s3-compatible-storage/revision-000.md).

**rclone config requirements verification depends on, each confirmed
against a real failure, not assumed:**

- `no_check_bucket = true` — a bucket-restricted leaf key can't satisfy
  rclone's pre-flight bucket-existence check the way an account-wide
  key can, so rclone falls back to `CreateBucket`, which a correctly
  least-privileged key has no rights to (independently documented
  against AWS S3 in rclone/rclone#4703 and #5119). **Open question,
  not yet resolved:** production's `cloud_sync`/`restore_discovery`
  `rclone.conf.j2` templates render the same kind of bucket-restricted
  key and don't set this — check Uptime Kuma's `cloud_sync` monitor and
  the buckets' actual recent object timestamps before assuming
  production isn't affected.
- `region` set explicitly — OCI's S3-compatible API 403s with
  `SignatureDoesNotMatch` if the bucket's region isn't stated and
  differs from the tenancy's home region. Resolved in both
  `rclone.conf.j2` templates: `region` is now rendered per target from
  `cloud_sync_targets[target].region` — reusing the same
  `secrets_generated['backblaze-b2-region']`/`['oci-region']` values
  already embedded in each provider's endpoint hostname for B2/OCI,
  and Cloudflare's documented `auto` for R2, which has no regional
  endpoints. Only rendered when set, so the Molecule fixtures'
  synthetic targets (which don't define one) are unaffected.
- A unique, timestamped verification-object key per rotation (see
  `_verify_marker_key`), not one fixed reused path — a fixed path
  breaks permanently the first time the bucket has any retention rule,
  since every write after the first is an overwrite of an
  already-retained object. Neither B2's nor OCI's write leaf can delete
  objects (by design), so these accumulate forever — accepted as
  negligible, since rotations are rare and each marker is a few bytes.

**R2's `--rotate` uses its cached admin token** rather than a
purpose-built delegate identity — same verify-then-revoke mechanics as
B2/OCI, broader blast radius if that token is ever compromised (see [R2's
section](scoping.md#cloudflare-r2--rotation-key-exists-now-but-its-not-scoped-like-the-other-two)). To update that cached token itself (as opposed to the
leaf keys it creates), see "Rotating the rotation credential itself"
below — `create_rotation_keys --provider r2 --rotate` — rather than
deleting `_rotation-key-cloudflare-r2-token` by hand, though that still
works too if you'd rather just fall back to prompting on next use.

### Rotating the rotation credential itself

Low-frequency,
human-attended, and none of the three auto-rotate on a schedule.

```sh
cd tools
python3 -m cloud_credentials.create_rotation_keys --provider b2 --rotate
python3 -m cloud_credentials.create_rotation_keys --provider oci --rotate --admin-email you@example.com
```

**B2** keeps the same verify-then-revoke shape leaf rotation has: mints
a new rotation key, confirms it can actually call `b2_list_keys`, only
then revokes the old one. If verification fails, the old key is left
untouched and still in use.

**OCI has no verify-then-revoke available for this credential — a
hard cutover, not a choice this repo made.** Regenerating a
Confidential Application's client secret
(`POST /admin/v1/AppClientSecretRegenerator`) invalidates the old
secret the instant it succeeds; OCI supports exactly one active secret
per app (confirmed via Oracle's own product-feedback forum — see [the
OCI section](scoping.md#oci--two-separate-credentials-two-separate-auth-models)). There is no "old value kept working if the new one
fails" guarantee here, unlike every other credential this repo
rotates. The new secret is cached immediately once returned, before
any verification round-trip — the old one is already gone regardless
of whether that verification succeeds, so withholding the cache write
on a verification failure would only discard the one copy of a value
OCI shows exactly once, for no benefit. If verification does fail,
the new secret is still cached (check it by hand), and the old one
cannot be recovered — Console's own "Regenerate" button on the app's
Configuration tab is the fallback if the cached value turns out
unusable. `--rotate` still re-verifies the leaf identities' classic-IAM
policies first, same as before — that part is unrelated and unaffected
by any of this.

Requires the master credential again (B2) or your personal admin OCI
identity (for leaf-identity re-verification only, not for the secret
regeneration itself) — this was never going to be a fully unattended
operation.

**R2** has no verify-then-revoke equivalent — Cloudflare's API
structurally can't mint a delegate credential for this at all (see
[ADR 0014 (R2 rotation credential)](../../../decisions/0014-r2-rotation-credential-cannot-be-narrowed/revision-000.md)) —
but it does have the same `--rotate` entry point now, closing a real
gap: create a new Custom Token in the Console first, then

```sh
cd tools
python3 -m cloud_credentials.create_rotation_keys --provider r2 --rotate
```

prompts for it and overwrites `_rotation-key-cloudflare-r2-token`
unconditionally — no hand-editing the cache file. There's genuinely
nothing to verify or revoke here: rolling the Custom Token in the
Console already revokes the old one immediately, before this command
ever runs, so unlike B2/OCI's `--rotate` there's no "old value kept
working if the new one fails" guarantee — there is no old value left
to fall back to by the time you're running this. `--provider r2`
(without `--rotate`) does the same idempotent-if-cached bootstrap the
other two providers get, and is never included in `--provider all`,
since it blocks on that Console step existing first.
