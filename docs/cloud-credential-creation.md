# Cloud Credential Creation — R2/B2/OCI

Two trust tiers, two scripts — except for R2, which has no tier
separation at all; see its section below for why.

- **`ansible/create_rotation_keys.py`** — run rarely, for B2 and OCI
  only. Takes each provider's master credential in memory only (never
  written to disk, never logged) and uses it to mint a narrower
  **rotation key**: scoped to creating/deleting keys, not to reading or
  writing backup data itself. The rotation key is what gets cached.
  `--provider r2` doesn't exist here — Cloudflare has no delegate
  credential to mint (confirmed live, see the R2 section).
- **`ansible/create_cloud_credentials.py`** — run routinely. This is
  what actually creates/rotates the 6 `cloud_sync`/restore-discovery
  credentials (`cloudflare-r2-write-*`/`-read-*`,
  `backblaze-b2-write-*`/`-read-*`, `oci-write-*`/`-read-*` in
  `secrets_registry.yaml` — **write** for `cloud_sync`'s own upload leg
  in `host_vars/storage.yaml`, **read** for the controller-side
  restore-discovery script, separate and not yet built — see
  `disaster-recovery.md`'s Restoring section once it exists). For B2
  and OCI, authenticates with the cached rotation key, never the master
  credential. For R2, it prompts for the master token directly, every
  time it actually needs to create a leg token — never cached, same
  in-memory-only handling everywhere else uses for master credentials.
  All six stay `format: manual` in the registry; this script is just an
  automated way to fill them in.

Rotation keys (B2, OCI) are cached to `ansible/files/secrets/` for now,
same as everything else in this repo. Moving that cache to an actual
secrets manager (OpenBao is the current candidate) is a separate,
not-yet-scoped subproject — see Future: Stage 2 below; nothing here
depends on it.

```sh
python3 ansible/create_rotation_keys.py --provider b2
python3 ansible/create_rotation_keys.py --provider oci --admin-email you@example.com
python3 ansible/create_cloud_credentials.py   # all three legs; prompts for R2's master token only if its leg credentials aren't cached yet
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

**Known gap: the script can't detect a stale policy behind an
already-cached rotation key.** `create_rotation_keys.py`'s top-level
check is "do the rotation key's cache files exist" — if they do, it
skips everything, including the 409-then-update logic that would
otherwise fix a policy that changed since the key was cached (exactly
what happened here: the first run cached a working keypair attached to
a policy that was later found to be wrong). Recovering from this needs
either deleting the `_rotation-key-oci-*` cache files and accepting a
new orphaned keypair, or fixing the policy directly in the Console —
there's no built-in way to force a policy-only re-check while keeping
the existing keypair. Worth building if this turns out to be a
recurring need rather than a one-time bootstrapping hiccup.

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
request.permission='OBJECT_CREATE'}` (no `OBJECT_DELETE`), read swaps
in `OBJECT_READ` — confirmed against Oracle's Policy Builder templates.

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
- The `UpdatePolicy` request shape used to fix an already-existing
  policy in place (a bare `{"statements": [...]}` PUT body) — the
  lookup-by-name path that feeds it is confirmed live, this specific
  PUT hasn't independently been exercised yet.

### Cloudflare R2 — no rotation tier exists, full stop

**There is no delegate credential for R2 — confirmed live, not a
missing feature.** The earlier design here assumed a "rotation key"
(created via the master token, cached, and itself able to mint leg
tokens) was possible, the same shape as B2's and OCI's. It isn't:
attempting to mint a token with `API Tokens Write` using a token that
was *itself* created via the API fails outright — `400 {"code": 1001,
"message": "sub-token is not allowed to have permissions to manage
other tokens"}`. Cloudflare allows exactly one level of
"this token can create other tokens" delegation, and it only exists
for tokens created directly in the dashboard by a human. Nothing
minted via the API can ever be granted that permission, regardless of
its own scope — there's no narrower variant to chase here, this is a
hard stop.

Consequently `create_rotation_keys.py` has no `r2` provider at all.
`create_cloud_credentials.py` prompts for the master token directly —
hidden input, memory only, same handling every other master credential
in this system gets — every time it actually needs to create a leg
token (skipped entirely if both legs are already cached, same
idempotency as everywhere else). The real cost: unlike B2 and OCI, R2's
leg-token creation/rotation can never run unattended — a human has to
be present to type in the master token each time, since nothing that
could stand in for it is ever cached. That's a genuine capability gap
versus the other two providers, not a design choice.

**The master token itself needs correcting too — confirmed live**
(`Unauthorized to access requested resource` on the very first API
call, before the sub-token issue above was even reached). Cloudflare's
own template reference table shows the dashboard's "Create Additional
Tokens" template grants `API Tokens Write` scoped to **User**, not
**Account** — it can only call `/user/tokens/...`, not the
`/accounts/{account_id}/tokens/...` endpoints this repo uses
throughout (chosen because R2 buckets are account resources). The
original assumption that "Create Additional Tokens" was an
"account-level" permission was never independently checked against
Cloudflare's docs before this. Create the master token as a **Custom
Token** instead — not the template — with **Account > Account API
Tokens > Edit**, scoped to the account. Its own permission_groups
lookup (used to find the R2-specific groups the leg tokens actually
get) matches by substring against known group names rather than exact
match, and prints every available name if nothing matches — a
mismatch here is a one-line fix, not another blind guess.

Once past both of those, there's no further ceiling to chase: the leg
tokens themselves are bucket-scoped (`Workers R2 Storage Bucket Item
Write`/`Read`, restricted to `homelab-backups`) and only ever hold
R2-specific permissions, never `API Tokens Write` — so they're not
subject to the sub-token restriction above at all, only the (now
removed) rotation key ever was. Practically, `cloud_sync`'s own
`rclone copy`-only design (never `sync`) is what actually prevents an
on-prem compromise from deleting R2 objects — see
`disaster-recovery.md`'s Threat model. R2's defense-in-depth here is
`copy`-vs-`sync`, not IAM.

## Rotation

**Rotating a leg key** (routine for B2/OCI, the *only* option for R2):
delete its cache file(s) under `ansible/files/secrets/`, re-run
`create_cloud_credentials.py --provider <r2|b2|oci>`. Both legs per
provider are checked independently, so rotating just the write leg
(delete only its two files) doesn't touch the read leg's cache. For
R2 specifically, this always prompts for the master token — there's no
cached credential to fall back on, so this is never unattended for R2
the way it can be for B2/OCI.

**Rotating a rotation key itself** (B2/OCI only, rare): delete its
cache file(s), re-run `create_rotation_keys.py --provider <b2|oci>` —
this needs the master credential again, so it's the one operation for
these two providers that isn't fully unattended. Doesn't apply to R2,
which has no rotation key to rotate.

**Known limitation, deliberately not built at either tier:** neither
script revokes the *old* provider-side key when it creates a new one —
you'll end up with an orphaned-but-still-valid key until you delete it
by hand (B2/OCI Console, or the R2 dashboard's token list). Auto-revoking
safely means confirming the new key actually works before killing the
old one, which is real design work, not something that falls out for
free the way file-based rotation does for `hex`/`uuid4` secrets.

## Future: Stage 2 (secrets manager)

Everything above is Stage 1: rotation keys and leg credentials both
land in `ansible/files/secrets/`, same as every other secret in this
repo. Stage 2 — replacing that cache with an actual secrets manager
(OpenBao is the current candidate) — is a separate, not-yet-scoped
subproject; nothing in Stage 1 depends on it or blocks it.

One thing worth carrying into that design specifically: R2 has no
cached credential at all — its master token is prompted fresh every
run (see its section above), which is the one place Stage 1 falls
short of the other two providers' level of automation. A secrets
manager holding that master token itself, gated by its own access
control and audit trail, could plausibly turn "a human types in the
token" into "an authorized policy-gated read" — worth evaluating
specifically for R2 when Stage 2 is actually scoped, since it's the
one provider Stage 1 couldn't fully solve on its own.
