# Cloud Credential Creation — R2/B2/OCI

Two trust tiers, two scripts:

- **`ansible/create_rotation_keys.py`** (this doc) — run rarely. Takes
  each provider's master credential in memory only (never written to
  disk, never logged) and uses it to mint a narrower **rotation key**:
  scoped to creating/deleting keys, not to reading or writing backup
  data itself. The rotation key is what gets cached.
- **`ansible/create_cloud_credentials.py`** — run routinely, covered in
  its own follow-up doc update. Authenticates with the cached rotation
  key, never the master credential.

Rotation keys are cached to `ansible/files/secrets/` for now, same as
everything else in this repo. Moving that cache to an actual secrets
manager is a separate, not-yet-scoped subproject; nothing here depends
on it.

```sh
python3 ansible/create_rotation_keys.py [--provider {r2,b2,oci,all}]
```

Safe to re-run — a rotation key whose cache files already exist is left
alone. Uses each provider's HTTP API directly, no `b2`/`oci` CLI binary
required — just the `requests`, `oci`, and `cryptography` packages
pinned in `pyproject.toml` (`oci` supplies only its
`oci.signer.Signer` request-signing helper; nothing here calls the
SDK's generated per-service clients).

## What "master credential" means per provider, and how scoped the resulting rotation key actually is

The achievable floor is genuinely different per provider — none of
this is a uniform "create/delete keys only" guarantee:

### Backblaze B2 — clean fit

Master: the account's existing master application key (B2 Console >
Application Keys), entered at the script's prompt, never cached. It
authorizes one `b2_create_key` call for a key scoped to `listKeys
writeKeys deleteKeys listBuckets`, restricted to `homelab-backups-b2`
— this key can create and delete application keys for that bucket but
can't itself read or write file contents. B2's native capability list
treats key-management capabilities as independent of file
capabilities, so this is a clean, real reduction in privilege versus
the master key.

**Needs live verification:** whether a bucket-restricted key can only
create further keys restricted to that same bucket, or can mint an
unrestricted one too — Backblaze's docs describe the `bucketId` field
but don't state this constraint explicitly. Worth a throwaway-key test
before trusting it.

### OCI — meaningful reduction, but not scoped to just the two leg users

Master: your personal/admin OCI identity via `~/.oci/config` — this is
the one master credential the script doesn't take interactively, since
OCI's auth model requires a persistent signing keypair rather than a
pasteable string. It's read once, by this script only, to do two
things: create the `homelab-cloud-sync-write`/`-read` IAM
users/groups/policies (idempotent — a 409 means it already exists and
gets looked up instead), and create a dedicated `homelab-key-rotation`
IAM user with its own freshly-generated RSA keypair (via
`cryptography`, uploaded through `UploadApiKey`) and a policy granting
exactly `manage customer-secret-keys` in the tenancy — nothing else, no
`manage users`/`groups`/`policies`, no object storage, no
compute/network/billing. That's what gets cached.

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

**Needs live verification, not yet confirmed:**

- User/group/policy writes must land in the tenancy's *home* region
  (Oracle's own docs), and the script doesn't check that
  `~/.oci/config`'s region is the home one. Console > Administration >
  Tenancy Details shows which region that is.
- The `UploadApiKey` request body's exact JSON field name for the PEM
  public key — every source found described it via SDK/Terraform field
  names (`key_value`, `keyValue`) rather than the raw REST JSON key.
  The script uses `"key"` as its best-supported guess; if the call
  400s, check this first.
- The 409-conflict fallback path (looking up an already-existing leg
  user by name via `GET /20160918/users?compartmentId=&name=`) hasn't
  been exercised against a real tenancy.

### Cloudflare R2 — platform limitation, not scoped down at all

**This is the one correction to `cloud-sync.md`'s original "without
delete/lifecycle-modification permission" line.** Cloudflare's own
docs on the `Create Additional Tokens` permission (needed to mint the
leg tokens) say plainly: a token holding it "can create tokens with
access to any of a user's resources" — there's no narrower variant.
The rotation key is therefore the *same permission* as the master
credential you paste in once, not a reduced one. The only lever
available is Cloudflare's own recommended mitigation: a short TTL (the
script sets `expires_on` 90 days out) rather than a standing, unexpired
token. IP-address filtering (also Cloudflare-recommended) isn't
automated here since it needs a stable egress IP the script doesn't
know — worth adding by hand via the dashboard if your homelab has one.

The leg tokens this rotation key creates are still bucket-scoped
(`Workers R2 Storage Bucket Item Write`/`Read`, restricted to
`homelab-backups`) — that part is unaffected by this gap, it's the
*rotation key itself* that can't be narrowed. Practically,
`cloud_sync`'s own `rclone copy`-only design (never `sync`) is what
actually prevents an on-prem compromise from deleting R2 objects — see
`disaster-recovery.md`'s Threat model. R2's defense-in-depth here is
`copy`-vs-`sync`, not IAM.

## Rotating a rotation key itself

Rare — delete its cache file(s) under `ansible/files/secrets/`, re-run
`create_rotation_keys.py --provider <r2|b2|oci>`. This needs the master
credential again, so it's the one operation in this whole system that
isn't fully unattended, by design.

**Known limitation, deliberately not built:** the script doesn't revoke
the *old* provider-side rotation key when it creates a new one — same
reasoning as leg-key rotation (covered in the follow-up doc update):
auto-revoking safely means confirming the new key works before killing
the old one, which is real design work, not something that falls out
for free.
