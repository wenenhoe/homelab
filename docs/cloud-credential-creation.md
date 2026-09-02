# Cloud Credential Creation — R2/B2/OCI

Two scripts, plus an audit tool:

- **`ansible/create_rotation_keys.py`** — run rarely, for B2 and OCI
  only. Takes each provider's master credential in memory only (never
  written to disk, never logged) and uses it to mint a narrower
  **rotation key**: scoped to creating/deleting keys, not to reading or
  writing backup data itself. The rotation key is what gets cached.
  `--provider r2` doesn't exist here — Cloudflare has no way to mint
  such a delegate credential via its API at all (confirmed live, see
  the R2 section); R2's admin token is cached differently, by
  `create_cloud_credentials.py` itself, below.
- **`ansible/create_cloud_credentials.py`** — run routinely. This is
  what actually creates/rotates the 6 `cloud_sync`/restore-discovery
  credentials (`cloudflare-r2-write-*`/`-read-*`,
  `backblaze-b2-write-*`/`-read-*`, `oci-write-*`/`-read-*` in
  `secrets_registry.yaml` — **write** for `cloud_sync`'s own upload leg
  in `host_vars/storage.yaml`, **read** for the controller-side
  restore-discovery script). B2 and OCI authenticate with their cached
  rotation key; R2 authenticates with its own cached admin token
  (`_rotation-key-cloudflare-r2-token` — prompted for once, then reused
  — see R2's section for why this one is a materially broader-blast-radius
  credential than the other two's). All six leg credentials stay
  `format: manual` in the registry; this script is just an automated
  way to fill them in.
- **`ansible/audit_secrets.py`** — run whenever, read-only. `--local`
  diffs `ansible/files/secrets/` against `secrets_registry.yaml` to
  flag cache files nothing currently references (e.g. leftover from a
  naming change). `--provider {oci,b2,r2,all}` lists each provider's
  actual write/read-leg credentials and flags any not matching the
  current cache as an orphan — e.g. a key from an interrupted rotation
  never cleaned up on the provider's side. Flags only; deleting
  anything it finds is a separate, deliberate step.

**Testing:** neither script is an Ansible role, so Molecule's per-host
model (`docs/molecule-testing.md`) doesn't apply. `ansible/tests/`
holds `unittest.TestCase`-style tests, run via pytest — every provider
HTTP call and `rclone` invocation mocked — via
`uv run pytest ansible/tests/ -v`, and wired into CI as `pr-checks.yml`'s
`python-unit-tests` job (see `docs/ci.md`).

Rotation keys/tokens (all three providers now) are cached to
`ansible/files/secrets/` for now, same as everything else in this
repo. Moving that cache to an actual secrets manager (OpenBao is the
current candidate) is a separate, not-yet-scoped subproject — see
Future: Stage 2 below; nothing here depends on it.

```sh
python3 ansible/create_rotation_keys.py --provider b2
python3 ansible/create_rotation_keys.py --provider oci --admin-email you@example.com
python3 ansible/create_cloud_credentials.py   # all three legs; prompts for R2's admin token once, if not yet cached
```

Safe to re-run either script — a credential whose cache files already
exist is left alone. Both use each provider's HTTP API directly, no
`b2`/`oci` CLI binary required — just the `requests`, `oci`, and
`cryptography` packages pinned in `pyproject.toml` (`oci` supplies only
its `oci.signer.Signer` request-signing helper; nothing here calls the
SDK's generated per-service clients).

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
`manage users` (scoped to `USER_SECRETKEY_ADD`/`_REMOVE`, still
tenancy-wide) and R2's `API Tokens Write` (account-wide) — none of the
three providers let you scope a key-management credential down to one
bucket/resource; that constraint appears structural to how "a
credential that can mint other credentials" works on all three, not
specific to any one of them.

The actual scoping this key gets, then, isn't bucket restriction — it's
that it holds zero file/bucket-data capabilities (no
`listFiles`/`readFiles`/`writeFiles`/`deleteFiles`), so even with
account-wide reach it can't touch backup contents itself, only mint
and revoke other keys.

**B2's leg keys need `listAllBucketNames`, confirmed live.** Unlike the
rotation key above, the write/read leg keys *are* bucket-restricted (to
`homelab-backups-b2`) — and Backblaze's own docs state plainly, across
three separate pages, that a bucket-restricted key needs
`listAllBucketNames` for S3-compatible-API access to work at all,
independent of whatever file capabilities it also holds. Missing it
produces a blanket `403 Forbidden` on the S3-compatible API — not a
capability-specific error, so it's easy to misdiagnose.
`rclone/rclone#5020` documents the same symptom independently.

**The write leg needs `readFiles` too, confirmed live.** rclone's S3
backend calls `HeadObject` on the destination before *every* `copy`,
fresh object or not, to decide skip-vs-upload — not `ListObjectsV2`,
despite rclone's own prose docs ("testing by size and modification
time") suggesting otherwise. B2 maps `HeadObject` to `readFiles`, not
`listFiles`. A write leg without `readFiles` fails outright on every
copy attempt (`operation error S3: HeadObject ... 403`), not just on
already-existing objects. So the write leg can read backup contents,
not just list and write them — the boundary this key actually holds is
narrower than "read-only excluded": it's `deleteFiles` being absent,
which is the property that matters for the threat model in
`disaster-recovery.md`, and it's untouched by this.

Both leg keys request `listBuckets listAllBucketNames listFiles
readFiles writeFiles` (write) / `listBuckets listAllBucketNames
listFiles readFiles` (read) — identical except for `writeFiles`. A
generic `Forbidden` with no named operation is a strong signal of an
outdated rclone binary (pre-1.75-ish); current versions name the
actual failing S3 call (`HeadObject`/`PutObject`/`ListObjectsV2`),
which narrows down which capability is missing far faster than
guessing from the error text alone.

### OCI — meaningful reduction, but not scoped to just the two leg users

Master: your personal/admin OCI identity via `~/.oci/config` — this is
the one master credential the script doesn't take interactively, since
OCI's auth model requires a persistent signing keypair rather than a
pasteable string. It's read once, by this script only, to do two
things: create the `homelab-cloud-sync-write`/`-read` IAM
users/groups/policies (idempotent at every step — user, group,
membership, and policy are each looked up instead of recreated if they
already exist, so a partially-completed prior run can be safely
resumed), and create a dedicated `homelab-key-rotation` IAM user with
its own freshly-generated RSA keypair (via `cryptography`, uploaded
through `UploadApiKey`) and a policy granting exactly `manage users`
scoped down to `USER_UPDATE`/`USER_SECRETKEY_ADD`/`USER_SECRETKEY_REMOVE`
— add and remove secret keys, nothing else beyond what `USER_UPDATE`
itself covers (plain `UpdateUser` — renaming/redescribing a user; not
`USER_UNBLOCK`, not `USER_DELETE`, not password reset, none of those
are granted). That's what gets cached.

**`manage customer-secret-keys` isn't a real OCI policy resource-type
— confirmed live** (`400 InvalidParameter: No permissions found`).
That name was inferred from the API object's name
(`CustomerSecretKey`) rather than checked against OCI's actual policy
vocabulary, which was a mistake. Credential management in OCI's policy
language lives under `manage users` with permission-level conditions.

**`USER_UPDATE` is required alongside `USER_SECRETKEY_ADD`/`_REMOVE`,
not optional — confirmed against Oracle's own permissions reference**
("Details for IAM with Identity Domains"), which lists `CreateSecretKey`
as needing `USER_UPDATE and USER_SECRETKEY_ADD` (an AND) and
`DeleteCustomerSecretKey` as `USER_UPDATE and USER_SECRETKEY_REMOVE`.
Every credential-mutating operation in that table follows the same
pattern — the specific permission alone is never sufficient. Omitting
`USER_UPDATE` produced a live `404 NotAuthorizedOrNotFound` on
`CreateCustomerSecretKey`; adding it, this policy statement went on to
successfully create both leg users' customer secret keys end to end —
this permission combination is confirmed correct in practice, not just
against the reference table. `USER_UPDATE`'s own scope (bare
`UpdateUser` only, nothing else) is the one real cost of this
requirement: the rotation identity can rename/redescribe any user in
the tenancy as a side effect of being grantable at all, not because
that's a capability anyone wanted — OCI bundles it into the same
permission that gates every per-user credential mutation.

**Fixed: policy drift behind an already-cached rotation key.**
`create_rotation_keys.py --provider oci` used to gate everything —
including the 409-then-update logic that fixes a changed policy —
behind "do the rotation key's cache files exist" (exactly what
happened here: the first run cached a working keypair attached to a
policy that was later found to be wrong, and a second run wouldn't
have caught it). The keypair-exists check now only gates keypair
*generation*; leg-identity and rotation-identity policy verification
run on every invocation regardless, the same way `oci_ensure_leg_identity`
already re-verified leg policies unconditionally. Re-running
`create_rotation_keys.py --provider oci --admin-email you@example.com`
is now enough to pick up a policy change without touching the cached
keypair — no flag needed, no cache files to delete. Confirmed live:
the fix applies immediately (a raw API re-GET right after reflects
it), but the Console's own policy detail view can lag visibly behind
that — don't trust the Console alone when checking whether this ran
correctly; re-GET via the API (or just wait a bit and refresh) instead
of concluding the fix didn't work.

**Identity-Domain tenancies require an email per user, confirmed
live** (`400 IdcsConversionError` from `CreateUser` without one).
Classic (non-domain) OCI IAM doesn't require this at all. Since email
must be unique per user and these are three service identities, not
people, `create_rotation_keys.py --provider oci` requires
`--admin-email you@example.com` and derives a distinct `+`-tagged
address per user (`you+homelab-cloud-sync-write@example.com`, etc.) off
it — one real mailbox you control, nothing fake. Required
unconditionally for the `oci` provider rather than detecting tenancy
type first; harmless on classic-IAM tenancies, where `email` is simply
optional.

The gap: this is tenancy-wide for customer-secret-keys, not scoped to
just the two `homelab-cloud-sync-*` users specifically. No confirmed
OCI policy condition (the way `target.bucket.name=` scopes object
storage) exists for narrowing identity-family resources to one named
user, as far as I've found — if you find one, this is worth
tightening.

The leg users' policies themselves: write gets `any
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
`OBJECT_DELETE` is still excluded from both legs; `OBJECT_OVERWRITE`
lets the write leg replace an existing object's content but not remove
one — a real (if currently unexercised, since every archive filename
embeds a unique timestamp and is never reused) capability beyond pure
append-only that wasn't granted before.

**Verified against this deployment's tenancy:** home region and the
region configured in `~/.oci/config` match — no mismatch, so no code
fix needed. Worth re-checking
(Console > Governance & Administration > Tenancy Management > Tenancy
Details, or `oci iam region-subscription list`) if this ever moves to
a different tenancy or the config's region changes.

**Confirmed, not a guess:** the `UploadApiKey` request body's JSON
field name for the PEM public key is `key` (Oracle's Python SDK model
reference documents it as the sole required attribute of
`CreateApiKeyDetails`, generated directly from their API spec). The
409-conflict fallback path — looking up an already-existing user by
name via `GET /20160918/users?compartmentId=&name=` — is also
confirmed live, having fired for real when a prior run failed partway
through and left users already created. The equivalent group lookup
uses the identical documented pattern but hasn't independently hit a
real 409 yet.

**Still needs a live test:**

- Whether an OCI policy condition can scope `manage users` to one
  named resource the way `target.bucket.name=` scopes object storage —
  every official example found only ever conditions storage/vault/compute
  resource families this way, never identity ones. Treating this as
  confirmed-absent unless proven otherwise.

### Cloudflare R2 — rotation key exists now, but it's not scoped like the other two

**A cached R2 rotation key is a materially different credential than
B2's/OCI's — accepted as a deliberate risk, not something worked
around.** Cloudflare's tokens API rejects granting `API Tokens Write`
to any token created via the API itself — `400 {"code": 1001,
"message": "sub-token is not allowed to have permissions to manage
other tokens"}`, confirmed live. That's a hard stop on ever *minting* a
delegate credential the way `create_rotation_keys.py` does for B2/OCI.
It does **not**, however, block *caching* a token a human already
created directly in the Console — that restriction is about creation,
not reuse. `r2_rotation_token()` in `create_cloud_credentials.py` does
exactly that: prompts once, caches to
`_rotation-key-cloudflare-r2-token`, and every later call (including
`--rotate`) reads the cache instead of re-prompting.

The trade-off this doesn't remove: because Cloudflare has no equivalent
of OCI's `any {request.permission='USER_SECRETKEY_ADD', ...}` — a
policy condition restricting *which* permissions a delegated identity
can grant — this cached token can mint a token with **any** permission
the account holder has (DNS, Zones, Workers, Access, billing,
everything), not just R2-scoped ones. B2's and OCI's rotation keys are
genuinely narrower than their master credentials; R2's cached token
**is** the master credential in every way that matters for blast
radius, just persisted to disk instead of re-typed each time. Accepted
here on the basis that (a) it was already being typed in from the same
password-manager entry every run, so caching it changes convenience,
not exposure to a new party, and (b) the planned Stage 2 secrets
manager migration (see below) is expected to narrow this properly —
this script isn't where that gets fixed.

**The master token itself needed correcting too — confirmed live**
(`Unauthorized to access requested resource` on the very first API
call, before the sub-token issue above was even reached). Cloudflare's
own template reference table shows the dashboard's "Create Additional
Tokens" template grants `API Tokens Write` scoped to **User**, not
**Account** — it can only call `/user/tokens/...`, not the
`/accounts/{account_id}/tokens/...` endpoints this repo uses
throughout (chosen because R2 buckets are account resources). The
original assumption that "Create Additional Tokens" was an
"account-level" permission was never independently checked against
Cloudflare's docs before this. Create the token as a **Custom
Token** instead — not the template — named
**`homelab-cloud-sync-r2-rotation-key`** (matching B2's rotation key
naming, with the `r2` disambiguator R2's own leg tokens already use)
— with **Account > Account API Tokens > Edit**, scoped to the account.
Its own permission_groups
lookup (used to find the R2-specific groups the leg tokens actually
get) matches by substring against known group names rather than exact
match, and prints every available name if nothing matches — a
mismatch here is a one-line fix, not another blind guess.

The leg tokens themselves stay properly bucket-scoped (`Workers R2
Storage Bucket Item Write`/`Read`, restricted to `homelab-backups`) and
only ever hold R2-specific permissions, never `API Tokens Write` — so
they're not subject to the sub-token restriction above at all, only the
rotation token is. Practically, `cloud_sync`'s own `rclone copy`-only
design (never `sync`) is what actually prevents an on-prem compromise
from deleting R2 objects — see `disaster-recovery.md`'s Threat model.
R2's defense-in-depth here is `copy`-vs-`sync` at the leg-token level,
not IAM narrowing at the rotation-token level, which is the part this
provider can't get to parity with B2/OCI on.

R2's S3-compat region is always `auto` — Cloudflare's own docs confirm
this is lenient (empty or `us-east-1` also alias to it), unlike OCI's
strict enforcement.

## Rotation

**`--rotate {write,read,both}`, all three providers now:**

```sh
python3 ansible/create_cloud_credentials.py --provider b2 --rotate write
python3 ansible/create_cloud_credentials.py --provider oci --rotate both
python3 ansible/create_cloud_credentials.py --provider r2 --rotate read
```

Order of operations, per leg: create a new provider-side key → verify
it actually works over the same rclone S3-compatible path
cloud_sync/restore-discovery use in production (a real `ListObjectsV2`
for the read leg, a real `PutObject` for the write leg — see
`verify_leg_via_rclone` in `create_cloud_credentials.py`) → only then
revoke the old key and overwrite its cache entry. **If verification
fails, both keys are left live and the cache is left untouched** — the
old key keeps working, the new (unverified, unrevoked) key is reported
so it can be investigated or deleted by hand; nothing is silently
rolled back or retried. Each leg is independent, so `--rotate write`
never touches the read leg's key or cache.

**Verification retries through each provider's key-propagation
window.** A brand-new leg credential isn't always immediately usable by
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

- `no_check_bucket = true` — a bucket-restricted leg key can't satisfy
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
  differs from the tenancy's home region; the same
  `rclone.conf.j2`-header gap noted above applies here too. Set for B2
  and R2 as well on the same principle, though only OCI has
  independently hit this failure mode.
- A unique, timestamped verification-object key per rotation (see
  `_verify_marker_key`), not one fixed reused path — a fixed path
  breaks permanently the first time the bucket has any retention rule,
  since every write after the first is an overwrite of an
  already-retained object. Neither B2's nor OCI's write leg can delete
  objects (by design), so these accumulate forever — accepted as
  negligible, since rotations are rare and each marker is a few bytes.

**R2's `--rotate` uses its cached admin token** rather than a
purpose-built delegate identity — same verify-then-revoke mechanics as
B2/OCI, broader blast radius if that token is ever compromised (see R2's
section above). Delete `_rotation-key-cloudflare-r2-token` to fall back
to prompting every time.

**Rotating the rotation credential itself** (B2/OCI's rotation keys,
or R2's cached admin token): none of the three auto-rotate or
auto-revoke this — it's a low-frequency, human-attended action.
B2/OCI: delete the cache file(s), re-run `create_rotation_keys.py
--provider <b2|oci>` (needs the master credential again). R2: create a
new Custom Token in the Console, overwrite
`_rotation-key-cloudflare-r2-token` by hand.

## Future: Stage 2 (secrets manager)

Everything above is Stage 1: rotation keys and leg credentials both
land in `ansible/files/secrets/`, same as every other secret in this
repo. Stage 2 — replacing that cache with an actual secrets manager
(OpenBao is the current candidate) — is a separate, not-yet-scoped
subproject; nothing in Stage 1 depends on it or blocks it.

One thing worth carrying into that design specifically: R2's cached
admin token (see its section above) is the one place Stage 1 falls
short of the other two providers' narrowing — it's cached now, same as
B2's/OCI's rotation keys, but unlike them it's genuinely
master-equivalent, since Cloudflare has no policy-condition mechanism
to restrict what a token-creating token can grant. A secrets manager
gating access to it with its own audit trail wouldn't narrow *what* it
can do, but would narrow *who/what can reach it* — worth evaluating
specifically for R2 when Stage 2 is actually scoped, since it's the
one provider Stage 1 couldn't bring to parity with the other two on
its own.
