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
| `play` | no-stop | `minecraft` → `backups` only (not `data`, `bluemap_*`, `extras`) | **2 days** |

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

### Minecraft: mirroring an already-quiesced volume

`minecraft`'s offsite job reads **only** the `backups` volume — the already
RCON-quiesced (`save-off`/`save-on`), compressed output of the existing
`itzg/mc-backup` service — never the live `data` volume. Two consequences:

- No stop-during-backup needed; the source is already static by the time
  this job touches it.
- Its `backup.cron` override (`30 4 * * *`) runs 30 minutes after
  `mc-backup`'s own `0 4 * * *`, so it never archives a tar mid-write.

Retention is intentionally **2 days, not 7** (`backup.retention_days`
override): `backups` is already a 7-day rolling window on-host
(~1.7GB/day × 7 ≈ 12GB) — 7 more full off-host copies of that same
near-duplicate window would cost ~84GB for little extra protection. 2
generations is enough to survive a bad/partial upload while `mc-backup`
still owns the actual version history. This override is safe precisely
*because* `minecraft` is the only app on `play` with a `backup:` entry —
see conflicting-overrides below for what happens when that's no longer
true.

### Conflicting overrides within a group

If two apps grouped together on the same host (same host, same
`stop_during_backup` value) declare different `backup.retention_days` or
`backup.cron`, `backup_agent`'s validation tasks fail the play loudly
rather than silently picking one app's value for both — see
`ansible/roles/backup_agent/tasks/main.yaml`. Resolve by aligning the
overrides, or by moving one app to its own host/group.

## Capacity

Rough budget against `storage`'s 256GB disk: minecraft's mirror (~12GB,
×2 retention ≈ 24GB) dominates; every other app's `data` volume is small
enough that even ×7 retention totals a low single-digit GB. Realistic usage
is ~25-30GB — comfortable headroom, with room to raise retention later if
you want deeper history for the smaller apps.

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

## S3 credentials

Auto-generated on first use, not prompted for — `seaweedfs_s3_access_key`/
`seaweedfs_s3_secret_key` (`group_vars/all/main.yaml`) use Ansible's `password`
lookup, which generates a random value once and caches it to a file on the
**controller** (not a managed host); every later lookup of that same path
returns the cached value instead of generating a new one:

```yaml
seaweedfs_s3_access_key: "{{ lookup('password', project_root ~ '/ansible/files/secrets/seaweedfs-s3-access-key chars=hexdigits length=32') }}"
seaweedfs_s3_secret_key: "{{ lookup('password', project_root ~ '/ansible/files/secrets/seaweedfs-s3-secret-key chars=hexdigits length=64') }}"
```

`chars=hexdigits` (the named charset, not a literal string) is deliberate:
these are opaque tokens, never hex-decoded, so mixed-case `a-fA-F` costs
nothing and gives more entropy per character. It also avoids writing a
literal hex-alphabet string next to a `_secret_key` name in source —
`gitleaks` flags that shape as a generic secret, even though it's just a
charset spec. The real generated values never get committed
(`ansible/files/secrets/` is gitignored).

Not the same pattern as `lldap`'s `openssl rand -hex 32` pipe, even
though both end up under `force: false`. `lldap`'s secret is generated
and consumed in one file on one host — any random value is fine since
`force: false` just locks in whichever render happens first. These
values need to match **across independently-rendered templates on
different hosts** (`storage`'s `s3-identity.json` and every
`backup_agent`'s `.env.*-group` files) — a raw pipe in each template
would generate a different value per host, and whichever rendered first
would permanently disagree with the rest. Only a controller-side cache
(what `password` does) keeps them all in sync.

The generated plaintext lives at `ansible/files/secrets/` on the
controller — gitignored, never committed, never touches a managed host
except via the rendered `.env`/`s3-identity.json` files (already
`no_log: true`/`mode: "0600"`).

**Rotating a credential**: delete the relevant file under
`ansible/files/secrets/`, then redeploy `storage` (so `s3-identity.json`
picks up the new value) and every host running `backup_agent` (so their env
files match again) — in either order, but both are required, or SeaweedFS
and its clients will disagree.

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
