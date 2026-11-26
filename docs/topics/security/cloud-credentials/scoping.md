# Cloud Credential Scoping — R2/B2/OCI

What each provider's master credential can and can't be narrowed to, how scoped the resulting rotation key actually is, and what the leaf credentials are restricted to. How the credentials are created is in [`creation.md`](creation.md).

## Per-provider scope

The achievable floor differs per provider; none of it is a uniform
"create/delete keys only" guarantee.

| | Backblaze B2 | OCI | Cloudflare R2 |
| :--- | :--- | :--- | :--- |
| Master credential | The account master application key, entered at a prompt, never cached | Your admin identity via `~/.oci/config` (leaf users and policies only) | A human-created Custom Token, cached |
| Rotation credential | A key with `listKeys writeKeys deleteKeys listBuckets` | The `homelab-oci-scim-rotation` Confidential Application (Identity Domains SCIM) | The cached master-equivalent token |
| Rotation scope | Account-wide; holds no file capabilities | Domain-wide User Administrator app role | Account-wide `API Tokens Write` |
| Leaf scope | Restricted to `homelab-backups-b2`; no `deleteFiles` | Bucket-scoped policy on `homelab-backups`; no `OBJECT_DELETE` | Restricted to `homelab-backups`; Item Write / Read |

No provider lets a key-management credential be scoped down to one
bucket or resource. What each leaf holds:

| Leaf | B2 capabilities | OCI permissions | R2 permission |
| :--- | :--- | :--- | :--- |
| Write | `listBuckets listAllBucketNames listFiles readFiles writeFiles` | `OBJECT_INSPECT`, `OBJECT_CREATE`, `OBJECT_OVERWRITE` | Bucket Item Write |
| Read | `listBuckets listAllBucketNames listFiles readFiles` | `OBJECT_INSPECT`, `OBJECT_READ` | Bucket Item Read |

Details per provider follow.

### Backblaze B2 — key-management can't be bucket-restricted, at all

Master: the account's existing master application key (B2 Console >
Application Keys), entered at the script's prompt, never cached. It
authorizes one `b2_create_key` call for a key scoped to `listKeys
writeKeys deleteKeys listBuckets` — **not** restricted to
`homelab-backups-b2`, or any bucket.

**B2 rejects the bucket restriction** (`400 Invalid capability for bucket-level
application key`): `listKeys`, `writeKeys` and `deleteKeys` are not capabilities a
bucket-restricted key may carry. OCI (User Administrator, domain-wide) and R2
(`API Tokens Write`, account-wide) are limited the same way.

The actual scoping this key gets, then, isn't bucket restriction — it's
that it holds zero file/bucket-data capabilities (no
`listFiles`/`readFiles`/`writeFiles`/`deleteFiles`), so even with
account-wide reach it can't touch backup contents itself, only mint
and revoke other keys.

**B2's leaf keys need `listAllBucketNames`.** Unlike the rotation key,
the write/read leaf keys *are* bucket-restricted (to
`homelab-backups-b2`), and a bucket-restricted key needs
`listAllBucketNames` for S3-compatible-API access to work at all,
whatever file capabilities it holds. Without it the API returns a
blanket `403 Forbidden`, not a capability-specific error
(`rclone/rclone#5020` shows the same symptom).

**The write leaf needs `readFiles` too.** rclone's S3 backend calls
`HeadObject` on the destination before *every* `copy`, fresh object or
not, to decide skip-vs-upload, and B2 maps `HeadObject` to `readFiles`,
not `listFiles`. A write leaf without it fails every copy
(`operation error S3: HeadObject ... 403`). So the write leaf can read
backup contents; the boundary it holds is `deleteFiles` being absent,
which is the property the threat model in
[`backup-threat-model.md`](../../disaster-recovery/backup-threat-model.md)
relies on.

A generic `Forbidden` that names no operation points to an outdated rclone; current
versions name the failing call (`HeadObject`, `PutObject`, `ListObjects`), which
identifies the missing capability.

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

The write leaf's `OBJECT_OVERWRITE` is needed for multipart uploads: without it
`CreateMultipartUpload` answers 404 `NoSuchBucket`, as this API does for any
authorization gap, and only for an archive large enough to go multipart (minecraft's).
Neither leaf has `OBJECT_DELETE`, so a lifecycle rule cleans up a failed multipart upload
([OCI window](../../disaster-recovery/cloud-sync.md#oci-window)).

**Identity-Domain tenancies require an email per user**
(`400 IdcsConversionError` from `CreateUser` without one).
Since these are three service identities, not people,
`create_rotation_keys --provider oci` requires
`--admin-email you@example.com` and derives a distinct `+`-tagged
address per user off it — one real mailbox you control, nothing fake.

**Rotation credential (Identity Domains SCIM,
[ADR 0109](../../../decisions/0109-knowing-a-cloud-credential-is-about-to-expire/revision-000.md)).**
Register it by hand:

1. Identity & Security > Domains > your domain > Integrated Applications > Add >
   Confidential Application, named exactly `homelab-oci-scim-rotation`
   (`OCI_SCIM_APP_DISPLAY_NAME` in `oci_bootstrap.py`: the tooling finds it by this name).
2. On its OAuth Configuration tab, enable the **Client credentials** grant. Skip Web Tier
   Policy.
3. Under Token Issuance Policy, grant the **User Administrator** app role.
4. **Activate** it: a new app is inactive, which is separate from its OAuth configuration.

`create_rotation_keys --provider oci` then prompts for the domain URL, client ID and client
secret, verifies them with a token exchange, looks up the app's SCIM id and caches all four
with `_rotation-key-oci-created-at` ([why self-tracked](expiry.md#credential-expiry)).

**User Administrator is sufficient** for what this repo needs from the
app: `POST /admin/v1/CustomerSecretKeys` (leaf key creation),
`GET /admin/v1/Apps?filter=...` (finding the app's own id), and
`POST /admin/v1/AppClientSecretRegenerator` (rotating its own secret).
Oracle's AppRole tables list the latter two under Security
Administrator, but User Administrator works.

User Administrator is a domain-wide role, not limited to the two leaf users, as no OCI
policy condition narrows identity-family resources the way `target.bucket.name=` scopes
object storage.

**SCIM specifics:**

- `CustomerSecretKey.user` takes the leaf user's OCID in its `ocid`
  field, not `value` — `value` is a different, shorter SCIM-internal id
  (max 40 characters) and rejects an OCID outright with
  `error.common.validation.stringExceedsMaxLimit`.
- `expiresOn` is immutable: set at create, never updated. Compare it as a parsed
  timestamp, since OCI echoes it back with milliseconds the request did not send.
- `accessKey` and `secretKey` are read-only and returned on create, so the SCIM call
  yields real S3 credentials.
- The app's client secret has no expiry field, and an app has one active secret, so
  regenerating it is a hard cutover ([Rotation](rotation.md#rotation)).
- Both the classic `GET /20160918/users/{id}/customerSecretKeys` and SCIM's
  `GET /admin/v1/CustomerSecretKeys?filter=user.ocid eq "..."` see SCIM-made keys.
  `audit.py --provider oci` uses SCIM, so auditing needs no `~/.oci/config`.

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
OCI's rotation keys. The difference is blast radius, not scrutiny: a read of
B2's application key or OCI's client secret raises an alert just as a read of
this token does ([watcher](../openbao/rotation-read-watcher.md#watched-set)). See
[ADR 0110 (R2 admin token custody)](../../../decisions/0110-the-r2-admin-token-as-the-rotation-credential/revision-000.md)
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
mismatch here is a one-line fix.

The leaf tokens themselves stay properly bucket-scoped (`Workers R2
Storage Bucket Item Write`/`Read`, restricted to `homelab-backups`) and
only ever hold R2-specific permissions, never `API Tokens Write` — so
none of the above applies to them, only to the rotation token. See
[ADR 0110 (R2 admin token custody)](../../../decisions/0110-the-r2-admin-token-as-the-rotation-credential/revision-000.md)
for what actually carries R2's defense-in-depth instead (the leaf
tokens' `copy`-vs-`sync` boundary, not IAM narrowing at the
rotation-token level).

R2's S3-compat region is always `auto` — Cloudflare's own docs confirm
this is lenient (empty or `us-east-1` also alias to it), unlike OCI's
strict enforcement.
