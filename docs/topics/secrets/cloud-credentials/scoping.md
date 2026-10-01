# Cloud Credential Scoping — R2/B2/OCI

What each provider's master credential can and can't be narrowed to, how scoped the resulting rotation key actually is, and what the leaf credentials are restricted to. How the credentials are created is in [`creation.md`](creation.md).

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
[`backup-threat-model.md`](../../disaster-recovery/backup-threat-model.md), and it's untouched by this.

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
[ADR 0016](../../../decisions/0016-oci-credential-creation-and-expiry/revision-000.md)):**
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
alongside a self-tracked `_rotation-key-oci-created-at` (see
[Credential expiry](expiry.md#credential-expiry) for why this one stays self-tracked).

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
  credential the way there is for leaf keys — see [Rotation](rotation.md#rotation) for
  what that means in practice.
- The classic API's `GET /20160918/users/{id}/customerSecretKeys` still
  sees keys created via SCIM, and SCIM's own
  `GET /admin/v1/CustomerSecretKeys?filter=user.ocid eq "..."` works too
  — both confirmed live. `openbao_utils/audit.py --provider oci` uses the
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
[ADR 0014](../../../decisions/0014-r2-rotation-credential-cannot-be-narrowed/revision-000.md)
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
[ADR 0014](../../../decisions/0014-r2-rotation-credential-cannot-be-narrowed/revision-000.md)
for what actually carries R2's defense-in-depth instead (the leaf
tokens' `copy`-vs-`sync` boundary, not IAM narrowing at the
rotation-token level).

R2's S3-compat region is always `auto` — Cloudflare's own docs confirm
this is lenient (empty or `us-east-1` also alias to it), unlike OCI's
strict enforcement.
