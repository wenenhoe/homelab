# Disaster Recovery — Stage 1: Off-host Backups

This is stage 1 of a staged DR plan: a separate VM (`storage`, `192.168.20.6`)
running [SeaweedFS](https://github.com/seaweedfs/seaweedfs) as a self-hosted
S3-compatible target, with an aggregated
[`offen/docker-volume-backup`](https://github.com/offen/docker-volume-backup)
agent per host (via a new `backup_agent` Ansible role) pushing
GPG-encrypted archives of selected named volumes to it nightly. No
cloud/off-site copy yet — that's a later stage.

## Why these tools, and why this shape

- Every app's real state already lives in a Docker-managed named volume,
  labelled and owned by the `compose` role (see [`volumes.md`](volumes.md)).
  A generic backup agent just mounts the volumes it cares about read-only —
  no per-app logic beyond declaring *which* volumes matter, via a `backup:`
  key on that app's `app_registry` entry (see below).
- `docker-volume-backup` doesn't do incremental/delta sync — every run tars
  whatever's mounted and uploads a new object; retention deletes old
  objects after N days. This is why aggregation groups apps by
  *retention/schedule agreement*, not just convenience.
- Backup targets are aggregated **per host, split into (at most) two
  groups** — not one-per-app, not one single instance. `backup_agent`
  scrapes this host's already-resolved `compose_apps` for any app
  declaring `backup.volumes`, and splits by `backup.stop_during_backup`:
  - **stop-during-backup group** — shares one `docker-socket-proxy`
    (scoped `CONTAINERS=1 POST=1 INFO=1`, same pattern as `lldap`'s
    certbot proxy), one archive, one schedule.
  - **no-stop group** — no proxy needed, backed up live.

  Two groups, not more or fewer: `docker-volume-backup` stops/restarts
  labeled containers **once per run**, not per-subdirectory, so mixing a
  "needs consistency" app with one that doesn't would stop the fast app
  for as long as the slow one's archive takes.
- `backup_agent`'s `compose.yaml` is **rendered from a Jinja template**,
  not copied verbatim like every other app's — the first templated
  compose file in this repo. It has to be: which volumes it mounts varies
  by host, and Compose can't express that conditionally from an env var.
- Retention/cron conflicts within a shared group are a **hard failure**,
  not a silent pick: if two apps grouped on the same host declare
  different `backup.retention_days`/`backup.cron`, the play stops with an
  explicit error. See `ansible/roles/backup_agent/tasks/main.yaml`.

## Storage host

`storage` joins `app_hosts` like any other app host purely so Caddy/BIND9
treat it consistently (own `caddy_domain`, own DNS zone) — it plays no part
in serving *other* hosts' DNS.

SeaweedFS runs in single-node "all-in-one" mode (`weed server -filer -s3`,
one process, one `data` volume). Right call for stage 1: the goal is "a
copy exists off the app host," not HA for the backup target itself.

Two surfaces, two different auth models:

- **Filer web UI** (`https://filer.store.{{ lab_domain }}`) — human-facing,
  fronted by Caddy + Tinyauth forward-auth + TLS, same as every other app.
- **S3 API** (`https://s3.store.{{ lab_domain }}`) — machine-facing, used
  only by `docker-volume-backup` sidecars. Routed `auth: false` in the
  registry deliberately: Tinyauth's forward-auth expects an interactive
  browser redirect, which a non-interactive S3 client can never complete.
  Its actual authentication is the S3 SigV4 access-key/secret pair in
  `docker/seaweedfs/configs/s3-identity.json.j2`, scoped to only the
  `homelab-backups` bucket (`Read`/`Write`/`List`/`Tagging`/`Admin`, all
  suffixed `:homelab-backups` — see the [SeaweedFS S3 Configuration
  wiki](https://github.com/seaweedfs/seaweedfs/wiki/S3-Configuration) for the
  action/resource-scoping syntax if you need to adjust it).

## Bucket creation

SeaweedFS does **not** auto-create a bucket on first `PUT`, even with
`Admin`-scoped credentials — confirmed the hard way, via a real
production failure (`NoSuchBucket`, 404) on the first scheduled backup
after this stage went live, despite the stop/restart and
archive-creation steps all working correctly.

`ansible/roles/seaweedfs_bucket` creates it explicitly and idempotently —
Play 5 in `deploy.yaml`, `storage` only, after SeaweedFS deploys (Play 4)
and before `backup_agent` could try to upload (Play 6). Mirrors the same
aws-cli approach already verified in
`ansible/roles/backup_agent/molecule/default/converge.yml`.

Kept out of `backup_agent` itself: bucket creation is a storage-side
setup concern (create the destination once), not something every
`backup_agent` host should redundantly handle.

## Encryption

Every archive is GPG-encrypted (`GPG_PUBLIC_KEY_FILE`) with an **asymmetric**
keypair — hosts only ever hold the public key (safe if it leaks; it can only
encrypt), the private key lives offline, never on any homelab host. This
means even a fully compromised `storage` + app host can't decrypt existing
backups. See the keygen walkthrough below before your first real deploy.

`ansible/files/backup-gpg-public-key.asc` ships as a **placeholder** — every
app's `configs` renders it in (`gpg-public-key.asc.j2` →
`lookup('file', ...)`), so replacing that one file updates it everywhere on
the next `ansible-playbook` run. Deploying with the placeholder still in
place produces backups nobody can decrypt — replace it first.

### Generating the keypair

Run this on your own workstation — never on `storage` or any app host:

```sh
gpg --full-generate-key
# Key type: RSA and RSA
# Key size: 4096
# Expiration: 0 (does not expire)
# Identity: any label, e.g. homelab-backup-2026

gpg --list-secret-keys --keyid-format=long
# note the hex string after "rsa4096/"

gpg --armor --export <key-id> > ansible/files/backup-gpg-public-key.asc
gpg --armor --export-secret-keys <key-id> > homelab-backup-private.asc
```

Store `homelab-backup-private.asc` somewhere durable and offline (password
manager, offline USB in a safe) with at least one redundant copy — losing it
makes every backup permanently unrecoverable.

## What's backed up

Declared per-app via a `backup:` key on its `app_registry` entry — see
`ansible/inventory/group_vars/all/app_registry.yaml`. `backup_agent` aggregates these
into (at most) two instances per host:

| Host | Group | Apps → volumes | Retention |
| :--- | :--- | :--- | :--- |
| `services` | stop-during-backup | `kms` → `data` | 7 days |
| `services` | no-stop | `wastebin` → `data` | 7 days |
| `security` | stop-during-backup | `beszel-hub` → `data`, `tinyauth` → `data` | 7 days |
| `security` | no-stop | `lldap` → `data`, `certs`, `creds`, `letsencrypt_conf`, `letsencrypt_lib` (not `scripts` — Ansible-managed, reproducible) | 7 days |
| `play` | no-stop | `minecraft` → `backups` only (not `data`, `bluemap_*`, `extras`) | 7 days |

Everything else in the registry has no `backup:` key and is explicitly out
of scope for stage 1 (your call — can lose it, or it's trivially
reproducible by redeploy).

### Consistency: stop-during-backup vs. live

`kms`, `beszel-hub`, and `tinyauth` each carry
`labels: [docker-volume-backup.stop-during-backup=true]` on their own
containers (unchanged from a per-app design) and are grouped into the
stop-during-backup instance on their host, which briefly stops all of them
together for one consistent archive run, then restarts them
(`BACKUP_STOP_DURING_BACKUP_LABEL`). A few seconds of downtime at 4am is a
good trade for a snapshot that isn't caught mid-write.

**Known limitations, accepted for stage 1 (single operator, trusted LAN)
— revisit if that trust model changes:**

- `docker-socket-proxy`'s `CONTAINERS=1`/`INFO=1` grant has no
  per-container ACL — it can start/stop any container on that host, not
  just the ones in its group. `INFO=1` is required: `docker-volume-backup`
  calls `/info` to check swarm vs. standalone before it can stop anything
  — without it, every stop-during-backup run fails immediately with a 403.
- Grouping couples downtime windows: apps sharing an archive are stopped
  for the full run, not just their own volume's slice. Revisit the
  grouping (or split further) if that gap ever matters in practice.

`lldap` and `wastebin` are backed up live, without stopping — your explicit
call for stage 1. If a restore ever turns up a corrupt SQLite file or LDAP
DB, that's the signal to add `stop_during_backup: true` to that app's
`backup:` entry.

### Conflicting overrides within a group

If two apps grouped together on the same host (same host, same
`stop_during_backup` value) declare different `backup.retention_days` or
`backup.cron`, `backup_agent`'s validation tasks fail the play loudly
rather than silently picking one app's value for both — see
`ansible/roles/backup_agent/tasks/main.yaml`. Resolve by aligning the
overrides, or by moving one app to its own host/group.

## S3 endpoint format

`offsite_backup_s3_endpoint` (`group_vars/all/main.yaml`) must be a **bare
hostname** — `s3.store.{{ lab_domain }}`, not `https://s3.store.{{ lab_domain }}`.
`docker-volume-backup`'s `AWS_ENDPOINT` env var is passed straight into the
underlying minio-go S3 client, which expects just `host[:port]`; a
scheme-prefixed value fails at runtime with `Endpoint url cannot have
fully qualified paths` (minio-go's `//` from the scheme gets misread as a
path segment). The scheme is a **separate** var,
`offsite_backup_s3_proto` (defaults `https`, consumed as
`AWS_ENDPOINT_PROTO`) — set it once here rather than embedding it in the
endpoint string, and every `backup-agent` instance across every host
picks it up consistently.

## Secrets

Every value this repo needs but doesn't want hardcoded — whether Ansible
can generate it itself or not — is resolved once and cached on the
controller by a single, reusable mechanism: the `secrets` role
(`ansible/roles/secrets/`), driven by a central registry
(`ansible/inventory/group_vars/all/secrets_registry.yaml`). It runs in
`deploy.yaml`'s Play 1, tagged `always` (same reasoning as `compose`'s
`preinit.yaml`: every downstream config template that reads a secret
needs it to already exist, regardless of which `--tags` subset a given
run uses — confirmed live via `--list-tasks --tags images`, which shows
`Include secrets role` at the same `always`-tagged level as
`preinit.yaml`, before Play 4 ever reaches `compose_app`/config
rendering).

This replaced four different ad hoc patterns that used to be spread
across the codebase: `deploy.yaml`'s entire `vars_prompt` block (typed in
on every run, both truly external credentials like the DigitalOcean API
key and plain config like `main_domain`), inline `lookup('password', ...)`
calls with a hand-built lookup-term string (`seaweedfs_s3_access_key`/
`seaweedfs_s3_secret_key`), `lookup('pipe', 'openssl rand -hex 32')`/a
`uuid` one-liner baked directly into a template (`lldap`'s three secrets,
`shlink`'s API key), and a gitignored `-e @secrets.yaml` file for
non-interactive runs. All of it — including any *future* secret or
config value — now goes through the same path:

1. Add an entry to `secrets_registry.yaml`:
   ```yaml
   secrets_registry:
     my-new-thing: { format: hex, length: 32 }
   ```
2. Reference `secrets_generated['my-new-thing']` from a plain var in
   `group_vars/all/main.yaml` (so a template only ever sees an ordinary
   variable name, never the registry key or the mechanism behind it):
   ```yaml
   my_new_thing: "{{ secrets_generated['my-new-thing'] }}"
   ```
3. Use `{{ my_new_thing }}` in the app's `configs/*.j2` template, with
   `no_log: true` on its `app_registry` entry if the value is a real
   secret (not just a hostname or timezone) — see "`no_log: true`"
   below for why.

No template should ever call `lookup('password', ...)` or
`lookup('pipe', ...)` directly again, and `deploy.yaml` should never grow
a new `vars_prompt` entry — if a new secret or config value needs one of
those, it needs a registry entry instead.

### Three formats

- **`hex`** (most generated secrets) — a thin, parameterized wrapper
  around `lookup('password', <path> chars=hexdigits length=<n>)`.
  `password` already *is* the generate-once-and-cache mechanism: per
  Ansible's own docs, "If the file already exists, no data will be
  written to it. If the file has contents, those contents will be read
  in as the password" — and its write path creates any missing parent
  directory itself (confirmed against `ansible-core`'s `password` lookup
  source: both its locking and its write path call `makedirs_safe()`
  first). The role's job here is just building that lookup term
  correctly from the registry so no call site hand-rolls it, and
  enforcing the `chars=hexdigits`-as-**named-charset** convention below.
- **`uuid4`** (`shlink-api-key` only, deliberately kept as a real UUID4
  rather than collapsed into a hex token) — `password`'s `chars=` option
  can only draw from a character set, which can never produce a
  structurally valid UUID4 (fixed version/variant nibbles), so this
  format has real generate-once-and-cache task logic instead: stat the
  cache file, generate via `python3 -c "import uuid; print(uuid.uuid4())"`
  only if missing, cache it with `mode: "0600"`, then always read it back
  — mirroring what `password` does internally, for a format it doesn't
  support natively. See `ansible/roles/secrets/tasks/ensure_secret.yaml`.
- **`manual`** (every remaining `vars_prompt` value — externally-issued
  credentials like the DigitalOcean API key, plain config like
  `main_domain`, and the two Beszel values that genuinely don't exist
  until after the hub's first boot) — Ansible can't generate any of
  these, so there's no generation step at all: the cache file must
  already exist before this task runs. **Missing entirely → the play
  fails immediately**, printing the registry entry's `description` and
  the exact command to create the file, rather than silently deploying
  with a blank credential nobody noticed. **Present but empty is a valid
  value** (reads back as `""`), not an error — existence is what's
  checked, not content. This is what lets `beszel-hub-key`/
  `beszel-agent-token` start out blank without failing every run until
  you fill them in: both are marked `allow_blank: true` in the registry,
  which `bootstrap_secrets.py` (below) reads to know it's fine to write
  an empty placeholder for those two specifically, instead of demanding
  a value that can't exist yet.

`chars=hexdigits` is a named charset, never a literal alphabet string, in
every hex secret's definition — deliberate, so `gitleaks` doesn't flag a
literal hex-alphabet string sitting next to a `_secret`/`_key`/`_pass`-shaped
variable name. `secrets_registry.yaml` only ever stores `format: hex`
plus a `length`, never a literal charset, for the same reason.

### Bootstrapping manual secrets

`manual` entries can't be generated, so before your first `deploy.yaml`
run, populate them once:

```sh
python3 ansible/bootstrap_secrets.py
```

Walks every `manual` entry in `secrets_registry.yaml`, skips anything
whose cache file already exists, and for everything else prompts for a
value (masked input, via `getpass`, for anything marked `sensitive:
true` in the registry) — re-prompting until something non-empty is
given, except for `allow_blank: true` entries, where pressing Enter
writes an empty placeholder on purpose. Safe to re-run any time: it
never touches a file that already exists, so re-running only fills in
whatever's still missing (a new registry entry someone added, or a
Beszel value you left blank the first time). Prefer hand-creating the
file yourself (`printf '%s' '<value>' >
ansible/files/secrets/<registry-key> && chmod 600
ansible/files/secrets/<registry-key>`) if you're scripting this instead
— the script is a convenience, not the only way in.

Values that can't be typed in ahead of time (Beszel's key/token) still
need the manual redeploy sequence documented in
[`beszel.md`](beszel.md): deploy once with them blank, retrieve the real
values from the hub's web UI, write them to their cache files (by hand,
or via `bootstrap_secrets.py` re-run), redeploy.

### Where the cache lives

Every generated value — `hex` and `uuid4` alike — lands at
`ansible/files/secrets/<registry-key>` on the **controller** (not a
managed host), one file per secret, gitignored
(`ansible/files/secrets/`), never committed. Real target hosts only ever
see the rendered `.env`/config file the value ends up in (already
`no_log: true`/`mode: "0600"` where relevant), never the cache directory
itself.

`seaweedfs-s3-access-key`/`seaweedfs-s3-secret-key` keep their existing
on-disk filenames — this registry migration was deliberately **not** a
rename, to avoid orphaning any value a real controller had already
cached before this change landed. Every other secret is free to follow
the same kebab-case convention from a clean slate.

**Rotating a credential**: delete the relevant file under
`ansible/files/secrets/`, then redeploy every host that renders a config
depending on it — this actually propagates now (see "`no_log: true`"
below for why an earlier version of this doc had to hedge that
statement). For `seaweedfs-s3-*` specifically this means `storage`
(so `s3-identity.json` picks up the new value) and every host running
`backup_agent` (so their env files match again) — in either order, but
both are required, or SeaweedFS and its clients will disagree. Values
consumed by only one host (`lldap`'s three secrets, `shlink`'s API key)
just need that one host redeployed.

### Why S3 credentials specifically need a controller-side cache

`offen/docker-volume-backup`'s S3 client and SeaweedFS's own identity
config are independently rendered on **different hosts**
(`storage`'s `s3-identity.json` and every `backup_agent` instance's
`.env.*-group` files) — a raw one-off generator in each template (the
`lldap`/`shlink` style, back when they used one) would produce a
different value per host, and whichever host rendered first would
permanently disagree with the rest. Only a controller-side cache (what
this role does for every secret, not just these two) keeps every
independently-rendered consumer in sync. `lldap`'s secrets don't have
this problem — each is generated and consumed in one file on one host —
but they go through the same mechanism anyway now, for consistency and a
single tested code path rather than two.

### `no_log: true` — why a secret never appears in `--diff` output

Every `app_registry` entry whose `configs` render a real secret (an API
key, token, or password — not just a hostname or timezone) sets
`no_log: true` on that config. This is the thing that actually matters
for secret-bearing configs, not `force`. Confirmed directly (not
assumed): a `template` task without `no_log` prints the full new
content to the console the moment it differs from what's already on the
target host — `ansible-playbook ... --diff` on a task rendering
`API_KEY=new-value` shows exactly that line, in plaintext, as a
`+` addition. `no_log: true` suppresses this completely, including on
task failure (Ansible replaces the entire result with `censored due to
'no_log: true'`), while a plain change still reports `changed: true` so
you can tell *that* something rendered without seeing *what*.

This risk exists on the **first** deploy too, not only a later
rotation — a file that doesn't exist yet is itself a "diff" (an
addition against nothing), so a secret-bearing config needs `no_log`
regardless of whether it's ever expected to change again.

**`force: false` is not the right tool for this**, and every
secret-bearing config in this registry has moved off it (see history —
it briefly followed the older `lookup('pipe', 'openssl rand -hex 32')`
templates' convention of relying on `force: false` for a completely
different reason: those had *no caching of their own*, so `force: false`
was the only thing stopping a fresh random value from being generated
on every single deploy. Now that idempotency lives in the controller-side
cache instead — see "Three formats" above — nothing left in this registry
actually needs `force: false`, and keeping it around would silently
defeat the "Rotating a credential" workflow above: `force: false` means
`ansible.builtin.template` leaves an existing destination file alone
**regardless of content**, so deleting the controller-side cache file and
redeploying would never actually propagate the new value to a host that
already has one rendered — a real gap an earlier version of this section
didn't call out clearly enough. Every current secret-bearing config
therefore just uses the module's own default (`force: true`, i.e.
"overwrite when content differs, leave alone when it doesn't" — normal
idempotent behavior) plus `no_log: true`.

### `force: false` — reserved for genuinely unreproducible state, nothing else

Every config in this registry defaults to `force: true` — this repo is
the source of truth, so a redeploy always overwrites a config that's
drifted from what its template would render, rather than leaving a
stale value in place indefinitely. `bind9`, `cobalt`, `kms`,
`seaweedfs`'s `env.j2`, `wetty`, and `minecraft` used to set
`force: false` too, despite none of them rendering a secret or holding
any state Ansible can't fully reconstruct from vars (a timezone, a
hostname, a domain) — audited by reading each template's actual
content, not assumed, and all six removed.

`force: false` earns its place only on a config whose destination can
hold real content Ansible has no way to reconstruct — something the
*app itself* writes back to the same file after Ansible first renders
it, where overwriting on every deploy would silently destroy something
no template could regenerate. Nothing in this registry currently needs
it. `dashy`'s `conf.yaml.j2` is an open question, not yet decided
either way: Dashy ships an in-UI config editor that saves back to
`data/conf.yml`, and nothing in this repo's compose file disables it.
If that editor is ever used, `force: true` would silently overwrite
whatever was changed there on the next deploy. See the comment on
`dashy`'s `app_registry` entry.

### Syncing the LDAP observer account password

`tinyauth-ldap-observer-password` is a special case worth calling out
explicitly: generating and caching the value is only half the story.
Tinyauth binds to lldap as a read-only account named `observer`
(`docker/tinyauth/configs/config.yaml.j2`'s `ldap.bindDn`), and **nothing
in this codebase creates that account or sets its password** — traced
through `docker/lldap/scripts/` and the rest of the repo, and confirmed
there's no scripted path today. lldap's own docs describe this as a
web-UI operation: create the user, add it to a read-only group
(`lldap_strict_readonly`/`lldap_readonly` depending on your lldap
version — check your deployed version's admin UI), and set its password
by hand.

**After (re)generating this secret, the operator must manually set the
`observer` account's password in lldap's admin web UI to the same
value**, or tinyauth's LDAP bind will fail with invalid credentials. Read
the cached value with:

```sh
cat ansible/files/secrets/tinyauth-ldap-observer-password
```

This was already true before this migration (the operator previously
typed this password into `vars_prompt` and then had to separately create
the matching lldap account) — the migration doesn't add a new manual
step, it just moves the value from "typed in on every run" to "generated
once and cached," which is why this note exists here rather than being
a new gap introduced by the change.

## Restore

`playbooks/restore.yaml` handles the generic case — extract a decrypted
archive back into one or more named volumes for a single app, stopping
and redeploying its compose stack around the operation. It's a thin
wrapper over `ansible/roles/restore`, where the actual logic — and its
[Molecule coverage](molecule-testing.md) — lives. That role's
`tasks/main.yaml` has a comment worth reading before touching either
file: this MUST stay a single play (`hosts: all`) with validation tasks
`delegate_to: localhost` inline, not split into a separate
controller-only validation play — that split was tried and confirmed to
silently skip validation entirely under `--limit <group>`, which is
exactly how this playbook is normally invoked.

Two independent gates each have to genuinely block the destructive steps,
both with their own Molecule scenario proving it via real side-effect
assertions (container `StartedAt`, volume content, scratch-volume/
archive-copy cleanup), not just an exit code:

- **Required vars / archive existence** — `restore_app`,
  `restore_archive_local_path`, `restore_volumes`, and the archive
  actually existing on the controller.
- **Human confirmation** — the `pause` prompt. It never waits when
  stdin genuinely isn't a tty (cron, systemd timers, CI), returning empty
  input immediately, so this gate fails **closed** there with no extra
  work. That's narrower than "any automated run, Molecule included,"
  though — a Molecule run launched from a real terminal inherits that
  terminal's tty, so `pause` *does* wait for real input there too.
  `restore_confirm` is a real three-state signal for exactly this reason
  (undefined → real prompt; explicitly `true`/`false` → deterministically
  confirmed/declined) — see the confirmation-gate comment in
  `roles/restore/tasks/main.yaml` for the full story. Both explicit
  values are `-e`-only, never defaulted or set in inventory/group_vars. A
  real operator only ever hits the undefined (real prompt) branch.

```sh
ansible-playbook playbooks/restore.yaml \
  -i inventory/inventory.yaml --limit services \
  -e restore_app=kms \
  -e restore_archive_local_path=/home/you/services-stop-group-2026-07-29T04-00-00.tar.gz \
  -e restore_volumes='["kms_data"]'
```

Since `backup_agent` aggregates apps per host/group, a shared archive can
contain more than one app's volumes when a group has multiple members
(e.g. `security`'s stop-group archive has both `beszel-hub_data` and
`tinyauth_data`). `restore_app`/`restore_volumes` don't need to match
everything in the archive — only what you're restoring.

Steps you do manually before running it (deliberately kept out of the
playbook — the private key should never touch a homelab host):

1. Pull the relevant object out of the `homelab-backups` bucket (filer web
   UI, or any S3 client pointed at `https://s3.store.{{ lab_domain }}` with
   the same credentials).
2. `gpg --decrypt` it with the offline private key into a plain `.tar.gz`.
3. Point `restore_archive_local_path` at that decrypted file.

The playbook then copies the archive to the target host, stops the app,
extracts the full archive into a scratch volume, locates the directory
matching each name in `restore_volumes` inside it (robust to however
`docker-volume-backup` nests paths — deliberately not assuming an exact
prefix), copies it over the live volume, cleans up, and redeploys. It pauses
for an explicit `yes` before touching anything, since this is destructive.

For `lldap` (multiple volumes in one archive), pass all of them:

```sh
-e restore_volumes='["lldap_data","lldap_certs","lldap_creds","lldap_letsencrypt_conf","lldap_letsencrypt_lib"]'
```

For `minecraft`, restoring `minecraft_backups` gets you back the on-host
rolling window of `mc-backup`-produced tars, not the live world directly —
you'd still need `itzg/mc-backup`'s own `restore-tar-backup` entrypoint
(`docker/minecraft/compose.restore.yaml`) as a second step to unpack the
newest of those tars into `minecraft_data`.

Not yet built: alerting if a nightly backup job fails silently — worth
wiring into `diun`/Beszel or a dedicated check once this has run for a
while.

## Not yet done / explicitly out of scope for stage 1

- Off-site/cloud replication of the `storage` host itself (stage 2).
- HA for SeaweedFS (single-node by design for now).
- Alerting on silent backup-job failures (see above).
