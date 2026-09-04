# Cloud Credential Creation — R2/B2/OCI

Two scripts, plus an audit tool:

- **`ansible/cloud_credentials/create_rotation_keys.py`** — run rarely.
  For B2, takes the master credential in memory only (never written to
  disk, never logged) and uses it to mint a narrower **rotation key**:
  scoped to creating/deleting keys, not to reading or writing backup
  data itself. For OCI, there's no credential to mint — a human
  registers a Confidential Application by hand in Console once (see
  the OCI section), and this script prompts for and caches its client
  ID/secret, alongside bootstrapping the two leaf identities' classic
  IAM policies with your personal admin config (`~/.oci/config`) —
  unrelated to the Confidential Application, still needed, see the OCI
  section for why. For R2, there's nothing to mint either — Cloudflare
  has no way to create such a delegate credential via its API at all
  (confirmed live, see the R2 section) — `--provider r2` here only
  caches (or re-caches, via `--rotate`) the Custom Token a human
  creates in the Console. Whatever gets cached either way is what
  `create_leaf_keys.py` actually reads.
- **`ansible/cloud_credentials/create_leaf_keys.py`** — run routinely.
  This is what actually creates/rotates the 6 `cloud_sync`/
  restore-discovery credentials (`cloudflare-r2-write-*`/`-read-*`,
  `backblaze-b2-write-*`/`-read-*`, `oci-write-*`/`-read-*` in
  `secrets_registry.yaml` — **write** for `cloud_sync`'s own upload leaf
  in `host_vars/storage.yaml`, **read** for the controller-side
  restore-discovery script). B2 and OCI authenticate with their cached
  rotation key; R2 authenticates with its own cached admin token
  (`_rotation-key-cloudflare-r2-token` — prompted for once, then reused
  — see R2's section for why this one is a materially broader-blast-radius
  credential than the other two's). All six leaf credentials stay
  `format: manual` in the registry; this script is just an automated
  way to fill them in.
- **`ansible/audit_secrets.py`** — run whenever, read-only. `--local`
  diffs `ansible/files/secrets/` against `secrets_registry.yaml` to
  flag cache files nothing currently references (e.g. leftover from a
  naming change). `--provider {oci,b2,r2,all}` lists each provider's
  actual write/read-leaf credentials and flags any not matching the
  current cache as an orphan — e.g. a key from an interrupted rotation
  never cleaned up on the provider's side. Flags only; deleting
  anything it finds is a separate, deliberate step.

**Testing:** neither script is an Ansible role, so Molecule's per-host
model (`docs/molecule-testing.md`) doesn't apply. `ansible/tests/`
holds `unittest.TestCase`-style tests, run via pytest — every provider
HTTP call and `rclone` invocation mocked — via
`uv run pytest ansible/tests/ -v`, and wired into CI as `pr-checks.yml`'s
`python-unit-tests` job (see `docs/ci.md`).

Rotation keys/tokens (all three providers) are cached to
`ansible/files/secrets/`, same as everything else in this repo — see
[ADR 0001](decisions/0001-credential-caching-stage-1-before-secrets-manager.md)
for why a secrets manager isn't part of this design yet.

```sh
cd ansible
python3 -m cloud_credentials.create_rotation_keys --provider b2
python3 -m cloud_credentials.create_rotation_keys --provider oci --admin-email you@example.com
python3 -m cloud_credentials.create_leaf_keys   # all three leaves; prompts for R2's admin token once, if not yet cached
```

Safe to re-run either script — a credential whose cache files already
exist is left alone. Both use each provider's HTTP API directly, no
`b2`/`oci` CLI binary required — just the `requests` and `oci` packages
pinned in `pyproject.toml` (`oci` supplies `oci.signer.Signer`, used
only for OCI's leaf-identity IAM bootstrap now — see the OCI section
for why that's a separate, unrelated auth model from the SCIM
credentials the rest of OCI's flow uses; nothing here calls the SDK's
generated per-service clients). `cryptography` is still pinned in
`pyproject.toml` but nothing in `cloud_credentials/` imports it
anymore as of the OCI SCIM migration (it only ever existed here for
OCI's now-removed RSA keypair generation) — worth removing as a
separate cleanup, not done as part of this migration.

## What "master credential" means per provider, and how scoped the resulting rotation key actually is

The achievable floor is genuinely different per provider — none of
this is a uniform "create/delete keys only" guarantee:

### Backblaze B2 — key-management can't be bucket-restricted, at all

Master: the account's existing master application key (B2 Console >
Application Keys), entered at the script's prompt, never cached. It
authorizes one `b2_create_key` call for a key scoped to `listKeys
writeKeys deleteKeys listBuckets` — **not** restricted to
`homelab-backups-b2`, or any bucket.

**Confirmed, not a guess — B2 rejects the bucket restriction outright**
(`400 Invalid capability for bucket-level application key`).
Backblaze's own docs on Application Keys enumerate every capability a
bucket-restricted key is allowed to carry, and `listKeys`/`writeKeys`/
`deleteKeys` aren't on that list — key management is inherently
account-wide on B2, full stop. Same shape of limitation as OCI's
Confidential Application role (User Administrator, domain-wide — see
the OCI section) and R2's `API Tokens Write` (account-wide) — none of
the three providers let you scope a key-management credential down to
one bucket/resource; that constraint appears structural to how "a
credential that can mint other credentials" works on all three, not
specific to any one of them.

The actual scoping this key gets, then, isn't bucket restriction — it's
that it holds zero file/bucket-data capabilities (no
`listFiles`/`readFiles`/`writeFiles`/`deleteFiles`), so even with
account-wide reach it can't touch backup contents itself, only mint
and revoke other keys.

**B2's leaf keys need `listAllBucketNames`, confirmed live.** Unlike the
rotation key above, the write/read leaf keys *are* bucket-restricted (to
`homelab-backups-b2`) — and Backblaze's own docs state plainly, across
three separate pages, that a bucket-restricted key needs
`listAllBucketNames` for S3-compatible-API access to work at all,
independent of whatever file capabilities it also holds. Missing it
produces a blanket `403 Forbidden` on the S3-compatible API — not a
capability-specific error, so it's easy to misdiagnose.
`rclone/rclone#5020` documents the same symptom independently.

**The write leaf needs `readFiles` too, confirmed live.** rclone's S3
backend calls `HeadObject` on the destination before *every* `copy`,
fresh object or not, to decide skip-vs-upload — not `ListObjectsV2`,
despite rclone's own prose docs ("testing by size and modification
time") suggesting otherwise. B2 maps `HeadObject` to `readFiles`, not
`listFiles`. A write leaf without `readFiles` fails outright on every
copy attempt (`operation error S3: HeadObject ... 403`), not just on
already-existing objects. So the write leaf can read backup contents,
not just list and write them — the boundary this key actually holds is
narrower than "read-only excluded": it's `deleteFiles` being absent,
which is the property that matters for the threat model in
`disaster-recovery.md`, and it's untouched by this.

Both leaf keys request `listBuckets listAllBucketNames listFiles
readFiles writeFiles` (write) / `listBuckets listAllBucketNames
listFiles readFiles` (read) — identical except for `writeFiles`. A
generic `Forbidden` with no named operation is a strong signal of an
outdated rclone binary (pre-1.75-ish); current versions name the
actual failing S3 call (`HeadObject`/`PutObject`/`ListObjectsV2`),
which narrows down which capability is missing far faster than
guessing from the error text alone.

### OCI — two separate credentials, two separate auth models

**Leaf identities (classic IAM, unchanged by the SCIM migration below):**
Master: your personal/admin OCI identity via `~/.oci/config` — read
once per `create_rotation_keys`/`--rotate` invocation, by this script
only, to create/verify the `homelab-cloud-sync-write`/`-read` IAM
users, groups, and bucket-scoped policies (idempotent at every step —
user, group, membership, and policy are each looked up instead of
recreated if they already exist). This has nothing to do with SCIM or
customer-secret-key creation; it's the same classic-IAM object-storage
policy scoping (`target.bucket.name='homelab-backups'`) as before.

The leaf users' policies: write gets `any
{request.permission='OBJECT_INSPECT',
request.permission='OBJECT_CREATE',
request.permission='OBJECT_OVERWRITE'}`, read swaps in `OBJECT_READ`
in place of the latter two. `OBJECT_OVERWRITE` is required alongside
`OBJECT_CREATE` specifically for multipart uploads — confirmed in
Oracle's own multipart-uploads documentation, which states this as a
named requirement beyond what a normal write policy needs. Without it,
`CreateMultipartUpload` 404s as `NoSuchBucket`, the same ambiguous
not-found-or-unauthorized response this API gives for every other
authorization gap — a single-part `PutObject` doesn't hit this, so it
went unnoticed until an archive large enough to trigger rclone's
multi-thread/multipart path (minecraft's) actually ran against OCI.
`OBJECT_DELETE` is still excluded from both leaves.

**Identity-Domain tenancies require an email per user, confirmed
live** (`400 IdcsConversionError` from `CreateUser` without one).
Since these are three service identities, not people,
`create_rotation_keys --provider oci` requires
`--admin-email you@example.com` and derives a distinct `+`-tagged
address per user off it — one real mailbox you control, nothing fake.

**Rotation credential (Identity Domains SCIM — replaces the old
OCID+PEM keypair entirely; see
[ADR 0016](decisions/0016-oci-expiry-via-scim-not-self-tracked-cache-files.md)):**
register a Confidential Application by hand in Console (Identity &
Security > Domains > your domain > Integrated Applications > Add >
Confidential Application), named exactly `homelab-oci-scim-rotation`
(`OCI_SCIM_APP_DISPLAY_NAME` in `oci_bootstrap.py` — SCIM search finds
it by this exact name, nothing else identifies it to this repo's
tooling). Enable the **Client credentials** grant on its OAuth
Configuration tab, skip Web Tier Policy (that's for browser-facing
apps behind a gateway — irrelevant here), grant the **User
Administrator** app role under Token Issuance Policy, then Activate
it — a freshly created app is inactive by default, a separate state
from its OAuth configuration; both are required before it will
authenticate at all. `create_rotation_keys --provider oci` then
prompts once for the domain URL, client ID, and client secret from
this app's Configuration tab, verifies them with a real token
exchange, looks up the app's own SCIM id, and caches all four
alongside a self-tracked `_rotation-key-oci-created-at` (see Credential
expiry below for why this one stays self-tracked).

**User Administrator is confirmed sufficient for everything this repo
needs from this app** — live-tested against a real tenancy for
`POST /admin/v1/CustomerSecretKeys` (leaf key creation),
`GET /admin/v1/Apps?filter=...` (finding the app's own id), and
`POST /admin/v1/AppClientSecretRegenerator` (rotating the app's own
secret). Oracle's own AppRole-to-endpoint tables list the latter two
under Security Administrator instead, which made this worth confirming
live rather than assuming the stricter table was the operative one —
it wasn't.

**The gap this replaces didn't fully close, it moved.** The old
rotation identity's classic-IAM policy was tenancy-wide `manage users`
— not scoped to just the two leaf users — because no confirmed OCI
policy condition narrows identity-family resources the way
`target.bucket.name=` scopes object storage. That specific policy is
gone now (there's no more classic rotation identity at all), but User
Administrator is a domain-wide app role, not scoped to two users
either. Same shape of trade-off, different mechanism.

**SCIM-specific things confirmed live, not inferred from the schema
alone:**

- `CustomerSecretKey.user` takes the leaf user's OCID in its `ocid`
  field, not `value` — `value` is a different, shorter SCIM-internal id
  (max 40 characters) and rejects an OCID outright with
  `error.common.validation.stringExceedsMaxLimit`.
- `expiresOn` is `mutability: immutable`, meaning settable at create
  (not server-computed) but never updatable afterward on an existing
  key. Round-trips as the same instant OCI echoes it back with —
  compare as parsed timestamps, not raw strings: OCI adds explicit
  milliseconds even when the request sent none.
- `accessKey`/`secretKey` are both `mutability: readOnly, returned:
  default` and genuinely populated on create — SCIM's create call
  produces real, usable S3-compatible credentials, not metadata layered
  on a key still created some other way.
- The Confidential Application's own client secret has no native
  expiry field on the `App` resource itself, and OCI supports exactly
  one active secret per app — regenerating (`AppClientSecretRegenerator`)
  is a hard cutover, not an overlap window (confirmed via Oracle's own
  product-feedback forum, where multi-secret support is an open feature
  request). There is no verify-then-revoke available for this specific
  credential the way there is for leaf keys — see Rotation below for
  what that means in practice.
- The classic API's `GET /20160918/users/{id}/customerSecretKeys` still
  sees keys created via SCIM, and SCIM's own
  `GET /admin/v1/CustomerSecretKeys?filter=user.ocid eq "..."` works too
  — both confirmed live. `audit_secrets.py --provider oci` uses the
  SCIM path, since it's the same credential everything else already
  authenticates with; nothing here depends on `~/.oci/config` for
  auditing.

### Cloudflare R2 — rotation key exists now, but it's not scoped like the other two

Cloudflare's tokens API rejects granting `API Tokens Write` to any
token created via the API itself — `400 {"code": 1001, "message":
"sub-token is not allowed to have permissions to manage other
tokens"}`. That rules out minting a delegate credential the way
`create_rotation_keys` does for B2/OCI; it does **not** block *caching*
a token a human already created directly in the Console, since that
restriction is about creation, not reuse. `r2_rotation_token()` in
`cloud_credentials/leaf_keys/r2.py` does exactly that: prompts once,
caches to `_rotation-key-cloudflare-r2-token`, and every later call
(including `--rotate`) reads the cache instead of re-prompting. This
cached token is master-equivalent, not a narrower delegate like B2's/
OCI's rotation keys — see
[ADR 0002](decisions/0002-r2-rotation-token-accepted-as-master-equivalent.md)
for why that's accepted rather than worked around.

**Create the master token as a Custom Token, not the "Create
Additional Tokens" template.** The template grants `API Tokens Write`
scoped to **User**, not **Account** — it can only call
`/user/tokens/...`, not the `/accounts/{account_id}/tokens/...`
endpoints this repo uses throughout (chosen because R2 buckets are
account resources); using the template fails on the first API call
with `Unauthorized to access requested resource`. Create a **Custom
Token** instead, named **`homelab-cloud-sync-r2-rotation-key`**
(matching B2's rotation key naming, with the `r2` disambiguator R2's
own leaf tokens already use), with **Account > Account API Tokens >
Edit**, scoped to the account. Its own `permission_groups` lookup
(used to find the R2-specific groups the leaf tokens actually get)
matches by substring against known group names rather than exact
match, and prints every available name if nothing matches — a
mismatch here is a one-line fix, not another blind guess.

The leaf tokens themselves stay properly bucket-scoped (`Workers R2
Storage Bucket Item Write`/`Read`, restricted to `homelab-backups`) and
only ever hold R2-specific permissions, never `API Tokens Write` — so
none of the above applies to them, only to the rotation token. See
[ADR 0002](decisions/0002-r2-rotation-token-accepted-as-master-equivalent.md)
for what actually carries R2's defense-in-depth instead (the leaf
tokens' `copy`-vs-`sync` boundary, not IAM narrowing at the
rotation-token level).

R2's S3-compat region is always `auto` — Cloudflare's own docs confirm
this is lenient (empty or `us-east-1` also alias to it), unlike OCI's
strict enforcement.

## Rotation

**One-time migration if you have an existing deployment:** this repo's
terminology changed from "leg" to "leaf" (write/read leaf key, matching
the standard root/intermediate/leaf credential-hierarchy vocabulary).
OCI's per-leaf IAM user OCID cache file followed suit — rename it under
`ansible/files/secrets/` before the next run:

```sh
cd ansible/files/secrets
mv _oci-leg-user-ocid-write _oci-leaf-user-ocid-write
mv _oci-leg-user-ocid-read  _oci-leaf-user-ocid-read
```

No other cache file is affected — every other provider's file names
(`cloudflare-r2-write-access-key`, `backblaze-b2-read-secret-key`,
`oci-write-access-key`, etc.) always used "write"/"read" directly, never
the word "leg" itself.

**One-time cleanup if you're migrating an existing OCI deployment to
SCIM (see [ADR 0016](decisions/0016-oci-expiry-via-scim-not-self-tracked-cache-files.md)):**
the classic-API rotation identity's local cache files and its OCI-side
IAM objects are both dead weight now — nothing reads or authenticates
with either, but nothing deletes them for you automatically.

Local cache files, safe to remove once you've confirmed
`oci-{write,read}-access-key`/`-secret-key`/`-scim-id` are all present
(the new code writes all three together):

```sh
cd ansible/files/secrets
rm -f _rotation-key-oci-user-ocid _rotation-key-oci-fingerprint \
      _rotation-key-oci-private-key.pem _rotation-key-oci-tenancy-ocid \
      _rotation-key-oci-region oci-write-created-at oci-read-created-at
```

On the Console side, delete the now-unused `homelab-key-rotation`
identity (Identity & Security > Domains > your domain), in this order —
its API signing key first, then the `homelab-key-rotation` policy, then
remove it from (or delete) the `homelab-key-rotation` group, then
delete the `homelab-key-rotation` user itself. This was a standing,
tenancy-wide `manage users` grant scoped to
`USER_UPDATE`/`USER_SECRETKEY_ADD`/`USER_SECRETKEY_REMOVE` (see ADR
0016's Context for why even that narrower grant was still tenancy-wide,
not scoped to the two leaf users) — worth actually removing, not
leaving unused, since an unused broad grant is exactly the kind of
thing worth not leaving lying around. `audit_secrets.py --local` flags
the stale local cache files above if you haven't cleaned them up yet;
it has no visibility into Console-side IAM objects, so that half is
manual.

**`--rotate {write,read,both}`, all three providers now:**

```sh
cd ansible
python3 -m cloud_credentials.create_leaf_keys --provider b2 --rotate write
python3 -m cloud_credentials.create_leaf_keys --provider oci --rotate both
python3 -m cloud_credentials.create_leaf_keys --provider r2 --rotate read
```

Order of operations, per leaf: create a new provider-side key → verify
it actually works over the same rclone S3-compatible path
cloud_sync/restore-discovery use in production (a real `ListObjectsV2`
for the read leaf, a real `PutObject` for the write leaf — see
`verify_leaf_via_rclone` in `cloud_credentials/verify.py`) → only then
revoke the old key and overwrite its cache entry. **If verification
fails, both keys are left live and the cache is left untouched** — the
old key keeps working, the new (unverified, unrevoked) key is reported
so it can be investigated or deleted by hand; nothing is silently
rolled back or retried. Each leaf is independent, so `--rotate write`
never touches the read leaf's key or cache.

**Verification retries through each provider's key-propagation
window.** A brand-new leaf credential isn't always immediately usable by
the provider's S3-compat API — the same request with an
already-propagated key succeeds, a just-created one fails until it
propagates. Each provider surfaces this differently and gives no way
to distinguish it from a genuine policy denial, so the retry gate
matches broadly on HTTP status alone (`StatusCode: 403` or
`StatusCode: 401`) rather than specific error text — accepted
deliberately: a real policy problem now takes the full retry window
(~885s / 14m45s) to surface as a failure instead of failing instantly,
but the alternative (no retry) means every manual re-run of a failed
`--rotate` mints and orphans a fresh provider-side key while waiting
out propagation by hand. Measured windows vary a lot by provider: OCI
60s–507s, B2 up to ~4 minutes, R2 15–30s — all comfortably inside the
current ceiling. Widen `_run_rclone_with_retry`'s `retries`/`delay` if
a real rotation ever exhausts it.

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
B2/OCI, broader blast radius if that token is ever compromised (see R2's
section above). To update that cached token itself (as opposed to the
leaf keys it creates), see "Rotating the rotation credential itself"
below — `create_rotation_keys --provider r2 --rotate` — rather than
deleting `_rotation-key-cloudflare-r2-token` by hand, though that still
works too if you'd rather just fall back to prompting on next use.

**Rotating the rotation credential itself:** low-frequency,
human-attended, and none of the three auto-rotate on a schedule.

```sh
cd ansible
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
per app (confirmed via Oracle's own product-feedback forum — see the
OCI section above). There is no "old value kept working if the new one
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
[ADR 0002](decisions/0002-r2-rotation-token-accepted-as-master-equivalent.md)) —
but it does have the same `--rotate` entry point now, closing a real
gap: create a new Custom Token in the Console first, then

```sh
cd ansible
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

## Future: secrets manager

See [ADR 0001](decisions/0001-credential-caching-stage-1-before-secrets-manager.md)
for why the current disk-cache design was chosen over a secrets
manager, and [ADR 0002](decisions/0002-r2-rotation-token-accepted-as-master-equivalent.md)
for the one gap (R2's cached admin token) worth carrying into that
design specifically when it's eventually scoped.

## Credential expiry

All 9 credentials (6 leaf, 3 rotation) expire after 90 days now — see
[ADR 0015](decisions/0015-credential-expiry-native-where-possible-self-tracked-where-not.md)
for B2/R2's native provider-side expiry, and
[ADR 0016](decisions/0016-oci-expiry-via-scim-not-self-tracked-cache-files.md)
for OCI's leaf keys, which are native too now (via SCIM `expiresOn`) —
only OCI's rotation credential (the Confidential Application's client
secret) stays self-tracked, since that specific resource has no native
expiry field of its own. Neither `create_leaf_keys.py` nor
`create_rotation_keys.py` needs a new flag for this — expiry is set
unconditionally on every create/rotate call, the same way capabilities
already are.

**B2** and **R2** enforce this themselves; an expired key/token simply
stops authenticating provider-side. **OCI's leaf keys** do too now,
via SCIM's native `expiresOn`. **OCI's rotation credential** doesn't —
the `App` resource has no expiry field on its client secret at all
(confirmed against Oracle's own SDK model), so a self-tracked
`_rotation-key-oci-created-at` cache file is advisory only, same as
every self-tracked credential in this repo. Nothing currently enforces
it beyond `check_freshness.py`'s own alert.

**R2's rotation admin token** is human-created in the Console (see its
section above) — set an expiration date on it there when you create
it; this script has no way to set one after the fact.

**`check_freshness.py`** reads all 9 back — natively for B2
(`b2_list_keys`), R2 (`GET .../tokens/{id}` for the leaf tokens,
`GET /user/tokens/verify` for the rotation token — see below), and
OCI's leaf keys (`GET /admin/v1/CustomerSecretKeys/{id}` via SCIM) —
from the self-tracked cache file for OCI's rotation credential only —
and reports each as fresh, expiring soon (within `expiry.WARNING_DAYS`,
30 days), expiring very soon (within `expiry.URGENT_DAYS`, 14 days),
past its window, or check-failed (couldn't be read at all — bad auth,
missing cache file, HTTP error). Only the last of those fails the
run's own exit code — `systemctl --user status` reflects whether the
check itself is healthy, not whether a credential happens to be due.

**The R2 rotation token is checked via `GET /user/tokens/verify`, not
any `/accounts/{account_id}/tokens` endpoint:** this admin token is a
Cloudflare **User API Token**, created via *My Profile > API Tokens*
exactly as `leaf_keys/r2.py`'s own prompt instructs — a different
resource category from "Account Owned API Tokens"
(`/accounts/{account_id}/tokens/*`, what the leaf tokens actually are,
since those *are* created via that API). Confirmed by directly
comparing all four combinations against a real token:
`GET /user/tokens/verify` succeeded (200, valid and active);
`GET /accounts/{account_id}/tokens/verify` and
`GET /accounts/{account_id}/tokens` (List) both only ever operate on
the Account-owned category and never see a User token no matter how
they're queried. `/user/tokens/verify` needs no `account_id` at all:
it verifies whichever token authenticated the request, scoped to the
calling user, not a specific account.

Any non-fresh result posts a Telegram alert to the `Backups` topic
(same one `telegram-notify-cloud-sync` already uses — see
[`telegram-notifications.md`](telegram-notifications.md)), using the
same cached `telegram-token`/`telegram-chat-id` every other consumer in
this repo reads from `ansible/files/secrets/`. Not routed through the
`telegram_notify` Ansible role — that's templated and deployed to
`managed_hosts`, and `controller` deliberately isn't one — so this
calls Telegram's `sendMessage` directly instead, same request shape.
No alert on an all-fresh run.

**This call uses `parse_mode=HTML`, not the legacy Markdown mode
`telegram_notify` and every other consumer in this repo use.**
Legacy Markdown requires escaping `` ` ``/`_`/`*`/`[` when literal, but
also forbids escaping inside an already-open entity (Telegram's own
documented rule) — a message composed by wrapping a bold header around
text containing one of those characters can't be made safe by
escaping alone. `detail` strings here embed arbitrary provider error
text and URLs, so that combination isn't a corner case, it's routine.
HTML has no equivalent trap: a `<b>` tag is either well-formed or it
isn't, and `_`/`*`/`` ` ``/`[` are always ordinary characters inside
or outside one. Only `&`, `<`, `>` are ever special; `_escape_telegram_html`
covers exactly those three, applied to `detail`.
`telegram-notifications.md` itself still documents the Markdown
convention correctly — accurate for `telegram_notify`'s own
static-template callers, which is all it ever claimed to cover.

The 30/14-day warning ladder exists specifically because B2 and R2
enforce their own expiry server-side: by the time either goes fully
stale, the credential has already stopped authenticating and
`cloud_sync` is already broken. A single threshold would still buy
lead time, but two grades of urgency (heads-up at a month out, urgent
at two weeks) means the reminder actually escalates as the deadline
gets closer instead of one flat repeated ping — see ADR 0015 for why
past-window alone wasn't enough.

```sh
cd ansible
python3 -m cloud_credentials.check_freshness
```

Runs unattended via a systemd **user** timer on `controller` — the
operator's own machine, where the cache already lives (see
`docs/architecture/system-overview.md`) — not through any Ansible role,
since `cloud_credentials` isn't one and doesn't deploy to any
`managed_hosts` entry. Install once, by hand:

```sh
cd ansible/cloud_credentials/systemd
# Edit check-freshness.service's WorkingDirectory to this clone's actual path first.
mkdir -p ~/.config/systemd/user
cp check-freshness.service check-freshness.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now check-freshness.timer
```

`Persistent=true` on the timer catches up on a missed weekly run once
the machine's next on — see ADR 0015's Consequences for the real limit
this still has on a machine that's off for longer than that.
