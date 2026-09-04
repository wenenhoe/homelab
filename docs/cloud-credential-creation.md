# Cloud Credential Creation — R2/B2/OCI

Two scripts, plus an audit tool:

- **`ansible/cloud_credentials/create_rotation_keys.py`** — run rarely,
  for B2 and OCI only. Takes each provider's master credential in
  memory only (never written to disk, never logged) and uses it to
  mint a narrower **rotation key**: scoped to creating/deleting keys,
  not to reading or writing backup data itself. The rotation key is
  what gets cached. `--provider r2` doesn't exist here — Cloudflare has
  no way to mint such a delegate credential via its API at all
  (confirmed live, see the R2 section); R2's admin token is cached
  differently, by `create_leaf_keys.py` itself, below.
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

### OCI — meaningful reduction, but not scoped to just the two leaf users

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
successfully create both leaf users' customer secret keys end to end —
this permission combination is confirmed correct in practice, not just
against the reference table. `USER_UPDATE`'s own scope (bare
`UpdateUser` only, nothing else) is the one real cost of this
requirement: the rotation identity can rename/redescribe any user in
the tenancy as a side effect of being grantable at all, not because
that's a capability anyone wanted — OCI bundles it into the same
permission that gates every per-user credential mutation.

**The keypair-exists cache check gates keypair *generation* only.**
Leaf-identity and rotation-identity policy verification run on every
`create_rotation_keys --provider oci` invocation regardless of whether
the keypair is already cached, the same way `oci_ensure_leaf_identity`
re-verifies leaf policies unconditionally. Re-running
`create_rotation_keys --provider oci --admin-email you@example.com` is
enough to pick up a policy change without touching the cached
keypair — no flag needed, no cache files to delete. A raw API re-GET
reflects a policy change immediately; the Console's own policy detail
view can lag visibly behind that, so treat the API (or `oci
iam policy get`) as the source of truth when confirming a policy
change took effect, not the Console alone.

**Identity-Domain tenancies require an email per user, confirmed
live** (`400 IdcsConversionError` from `CreateUser` without one).
Classic (non-domain) OCI IAM doesn't require this at all. Since email
must be unique per user and these are three service identities, not
people, `create_rotation_keys --provider oci` requires
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

The leaf users' policies themselves: write gets `any
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
`OBJECT_DELETE` is still excluded from both leaves; `OBJECT_OVERWRITE`
lets the write leaf replace an existing object's content but not remove
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

**Confirmed live:** the existing rotation identity's Signature V1 auth
(`OCISigner`) does not work against the Identity Domains SCIM API —
the endpoint that carries a real, native `expiresOn` (see
[ADR 0015](decisions/0015-credential-expiry-native-where-possible-self-tracked-where-not.md)).
A read-only `GET /admin/v1/Schemas` signed with it comes back
`401 error.common.common.accessDenied`. `cloud_credentials/spikes/oci_scim_auth_check.py`
is the script that confirmed this, kept around in case a future
tenancy or auth setup changes the answer:

```sh
cd ansible
python3 -m cloud_credentials.spikes.oci_scim_auth_check https://idcs-xxxxxxxxxxxx.identity.oraclecloud.com
```

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
section above). Delete `_rotation-key-cloudflare-r2-token` to fall back
to prompting every time.

**Rotating the rotation credential itself:** low-frequency,
human-attended, and none of the three auto-rotate on a schedule — but
B2/OCI now have the same zero-downtime shape leaf rotation already has:

```sh
cd ansible
python3 -m cloud_credentials.create_rotation_keys --provider b2 --rotate
python3 -m cloud_credentials.create_rotation_keys --provider oci --rotate --admin-email you@example.com
```

Mints a new rotation key, verifies it can actually do its job, only
then revokes the old one — same verify-before-revoke shape as leaf
rotation, one level up. Verification differs by provider because
what "actually do its job" means differs: B2's new key must
successfully call `b2_list_keys`; OCI's new key must successfully
create *and* delete a throwaway customer secret key on the write leaf,
not just authenticate — its policy is conditioned on exactly
`USER_UPDATE`/`USER_SECRETKEY_ADD`/`USER_SECRETKEY_REMOVE`, not a
blanket read grant, so a lighter check (like fetching the user record)
could pass or fail for reasons unrelated to whether the key can
actually rotate leaf credentials. If verification fails, the old key
is left untouched and still in use, same failure-handling guarantee as
leaf rotation. Requires the master credential again (B2) or your
personal admin OCI identity (OCI), same as the very first bootstrap —
this was never going to be a fully unattended operation.

**OCI's new API signing key also goes through the same key-propagation
window leaf keys do — confirmed live, not assumed:** a real rotation
401'd against the verification call for a full ~180s before OCI
recognized the new key, on a from-scratch diagnostic that ruled out
everything else first (the key genuinely existed provider-side and was
being correctly signed against — this was purely OCI's own identity
plane catching up). `_verify_rotation_key` retries broadly on 401 or
403 for the same reason `_run_rclone_with_retry` does above — OCI gives
no way to distinguish "not propagated yet" from a genuine policy denial
in the response — with the same default 60 retries / 15s delay
(~900s ceiling), comfortably above the measured 180s. B2's rotation-key
verification (`b2_list_keys`) hasn't hit this in practice and has no
retry loop; add one the same way if it ever does.

**R2** has no equivalent: create a new Custom Token in the Console,
overwrite `_rotation-key-cloudflare-r2-token` by hand — Cloudflare's
API structurally can't mint a delegate credential for this at all (see
[ADR 0002](decisions/0002-r2-rotation-token-accepted-as-master-equivalent.md)).

## Future: secrets manager

See [ADR 0001](decisions/0001-credential-caching-stage-1-before-secrets-manager.md)
for why the current disk-cache design was chosen over a secrets
manager, and [ADR 0002](decisions/0002-r2-rotation-token-accepted-as-master-equivalent.md)
for the one gap (R2's cached admin token) worth carrying into that
design specifically when it's eventually scoped.

## Credential expiry

All 9 credentials (6 leaf, 3 rotation) expire after 90 days now — see
[ADR 0015](decisions/0015-credential-expiry-native-where-possible-self-tracked-where-not.md)
for why B2/R2 use native provider-side expiry and OCI uses a
self-tracked cache-file timestamp instead, and why neither `create_leaf_keys.py`
nor `create_rotation_keys.py` needs a new flag for this — expiry is set
unconditionally on every create/rotate call, the same way capabilities
already are.

**B2** and **R2** enforce this themselves; an expired key/token simply
stops authenticating provider-side. **OCI** doesn't — its classic
Identity API has no expiry concept at all, so a self-tracked
`<credential>-created-at` cache file (e.g. `oci-write-created-at`,
`_rotation-key-oci-created-at`) is advisory only. Nothing currently
enforces it beyond `check_freshness.py`'s own alert.

**R2's rotation admin token** is human-created in the Console (see its
section above) — set an expiration date on it there when you create
it; this script has no way to set one after the fact.

**`check_freshness.py`** reads all 9 back — natively for B2 (`b2_list_keys`)
and R2 (`GET .../tokens/{id}` / `.../tokens/verify`), from the
self-tracked cache files for OCI — and reports each as fresh, expiring
soon (within `expiry.WARNING_DAYS`, 30 days), expiring very soon (within
`expiry.URGENT_DAYS`, 14 days), past its window, or
check-failed (couldn't be read at all — bad auth, missing cache file,
HTTP error). Only the last of those fails the run's own exit code —
`systemctl --user status` reflects whether the check itself is
healthy, not whether a credential happens to be due.

Any non-fresh result posts a Telegram alert to the `Backups` topic
(same one `telegram-notify-cloud-sync` already uses — see
[`telegram-notifications.md`](telegram-notifications.md)), using the
same cached `telegram-token`/`telegram-chat-id` every other consumer in
this repo reads from `ansible/files/secrets/`. Not routed through the
`telegram_notify` Ansible role — that's templated and deployed to
`managed_hosts`, and `controller` deliberately isn't one — so this
calls Telegram's `sendMessage` directly instead, same request shape.
No alert on an all-fresh run.

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
