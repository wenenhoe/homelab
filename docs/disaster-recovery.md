# Disaster Recovery — Off-host and Cloud Backups

A separate VM (`storage`, `192.168.20.6`) runs
[SeaweedFS](https://github.com/seaweedfs/seaweedfs) as a self-hosted
S3-compatible target. One [`offen/docker-volume-backup`](https://github.com/offen/docker-volume-backup)
agent per host (`backup_agent` role) pushes GPG-encrypted archives of
selected named volumes to SeaweedFS — nothing else. Cloud coverage
(Cloudflare R2 / Backblaze B2 / OCI Object Storage) is planned as a
separate `cloud_sync` role running only on `storage`, reading already-
encrypted objects out of SeaweedFS and copying them onward — not yet
built; see "Threat model" below for why it's designed this way, and
"What's backed up" for current SeaweedFS-only coverage.

S3 credential generation/rotation is covered in [`secrets.md`](secrets.md),
not here.

## Threat model

Every app host's `backup_agent` holds a live, write-capable S3
credential — the whole point of an offsite backup is surviving
compromise of the host it's protecting, so that credential's reach
matters as much as its existence. Two constraints follow from that:

- **Cloud credentials never touch an app host.** R2/B2/OCI write access
  exists only on `storage` (`cloud_sync`, once built) — the smallest,
  least-exposed host in the fleet (nothing user-facing runs there; see
  the compose_apps list per host in `ansible/inventory/host_vars/`).
  Compromising `services`, `security`, or `play` yields no cloud
  credential of any kind, only that host's own narrow SeaweedFS access
  below.
- **Each app host's SeaweedFS identity is scoped to its own prefix
  only** (`docker/seaweedfs/configs/s3-identity.json.j2`,
  `Write:homelab-backups/<hostname>-*` etc.) — a compromised `services`
  can still tamper with `services`' own SeaweedFS archives (unavoidable:
  whatever produces a backup needs some write path to stage it) but
  can't touch `security`'s or `play`'s.

**Automated coverage exists now** (`ansible/roles/seaweedfs_bucket/molecule/identity_scoping`) — it renders the real `s3-identity.json.j2` against a live throwaway SeaweedFS target with two fake backup hosts, and asserts cross-prefix write/read are denied and Admin actions aren't available to a scoped identity. That test's own exact failure-message matching couldn't be verified without a running SeaweedFS instance at the time it was written — if you're the first to actually run it, and the `is failed` assertions pass but look fragile, that's expected; the substring checks were my best guess at the real error shape, not a confirmed one.

## Architecture

- Volumes to back up are declared per-app via a `backup:` key on the app's
  `app_registry` entry — the agent has no per-app logic beyond that.
- One `docker-volume-backup` container per host runs one schedule per
  app, always to SeaweedFS. `docker-volume-backup` does full
  tar-and-upload per run, no delta sync — a schedule's cost scales with
  that one app's volume size, not with anything else sharing the
  container.
- Apps that need to be stopped for a consistent snapshot set
  `docker-volume-backup.stop-during-backup=<app-name>` on their own
  compose service (their own name, not a shared `true`) and
  `backup.stop_during_backup: true` in `app_registry.yaml`. Each such
  app's schedule then sets `BACKUP_STOP_DURING_BACKUP_LABEL=<app-name>`
  to match. That match is scoped per schedule file, not once for the
  whole container: a schedule backing up app A never touches app B's
  uptime, even though every app's schedules share one container.
  `docker-socket-proxy` (`CONTAINERS=1 POST=1 INFO=1`) is only added to
  the compose file at all if at least one app on the host needs stopping.
- `backup_agent`'s `compose.yaml` is rendered from a Jinja template (the
  only templated compose file in this repo) since mounted volumes vary
  per host.
- No retention/cron conflict validation is needed — every schedule is
  independent, so there's nothing to conflict.

## Storage host

SeaweedFS runs single-node (`weed server -filer -s3`) — sufficient for "a
copy exists off-host," not HA for the backup target itself.

- **Filer web UI** (`https://filer.store.{{ lab_domain }}`) — human-facing,
  Caddy + Tinyauth + TLS like every other app.
- **S3 API** (`https://s3.store.{{ lab_domain }}`) — machine-facing only.
  Registered `auth: false` (Tinyauth's forward-auth needs an interactive
  redirect a non-interactive S3 client can't complete). Auth is instead
  the per-identity S3 SigV4 keypairs in
  `docker/seaweedfs/configs/s3-identity.json.j2` — one broad
  bucket-admin identity (bucket creation only) plus one narrow,
  path-scoped identity per `backup_agent` host. See "Threat model"
  above for why, and the [SeaweedFS S3 Configuration
  wiki](https://github.com/seaweedfs/seaweedfs/wiki/S3-Configuration) to
  adjust the scoping.

## Bucket creation

SeaweedFS does not auto-create a bucket on first `PUT`, even with
`Admin`-scoped credentials. `ansible/roles/seaweedfs_bucket` creates it
explicitly (Play 5 in `deploy.yaml`, `storage` only, after SeaweedFS
deploys and before `backup_agent` runs). Kept out of `backup_agent` itself
since bucket creation is a one-time storage-side concern.

## Encryption

Archives are GPG-encrypted (`GPG_PUBLIC_KEY_FILE`) with an asymmetric
keypair: hosts hold only the public key; the private key stays offline and
is never on any homelab host, so a compromised host can't decrypt existing
backups.

`ansible/files/backup-gpg-public-key.asc` ships as a placeholder — replace
it before your first real deploy, or backups will be unrecoverable.

### Generating the keypair

Run on your own workstation, never on `storage` or an app host:

```sh
gpg --full-generate-key
# Key type: RSA and RSA, size: 4096, expiration: 0

gpg --list-secret-keys --keyid-format=long
# note the hex string after "rsa4096/"

gpg --armor --export <key-id> > ansible/files/backup-gpg-public-key.asc
gpg --armor --export-secret-keys <key-id> > homelab-backup-private.asc
```

Store `homelab-backup-private.asc` offline (password manager, offline USB)
with a redundant copy — losing it makes every backup unrecoverable.

## What's backed up

| Host | App → volumes | Stopped during backup | Retention |
| :--- | :--- | :--- | :--- |
| `services` | `kms` → `data` | yes (`kms`) | 7 days |
| `services` | `wastebin` → `data` | no | 7 days |
| `security` | `beszel-hub` → `data` | yes (`beszel-hub`) | 7 days |
| `security` | `tinyauth` → `data` | yes (`tinyauth`) | 7 days |
| `security` | `lldap` → `data`, `certs` | no | 7 days |
| `play` | `minecraft` → `backups` only | no | 7 days |

Apps without a `backup:` key in `app_registry.yaml` are out of scope.
All of the above go to SeaweedFS only, for now — see the note at the
top of this doc and "Threat model" above for the planned `cloud_sync`
role.

`lldap` is deliberately never stopped — it's the auth backend, and every
other app behind Caddy/tinyauth loses login for the stop window, a
bigger blast radius than the SQLite-consistency risk it'd guard against.
`minecraft`'s `backups` volume is already RCON-quiesced by `itzg/mc-backup`
before this ever reads it (`docker/minecraft/compose.yaml`), so stopping
`mc` here would add downtime with no consistency benefit. If a restore
ever turns up a corrupt SQLite/LDAP file for `wastebin`/`lldap`, add
`stop_during_backup: true` and the matching compose label (see
Architecture above) rather than assuming it's needed by default.

`app_registry.yaml`'s `backup.cloud_targets` (e.g. minecraft's
`[seaweedfs, oci]`) is currently dormant data — `backup_agent` no longer
reads it. It's there for `cloud_sync` to consume once built, meaning
"also copy this app's SeaweedFS archives to OCI." Don't read anything
into it being present today.

**Migration note:** every app host previously also pushed directly to
R2/B2/OCI (a design this patch replaces — see "Threat model"). Any
objects already sitting in those buckets from that period are now
orphaned: nothing will prune them, and nothing will add to them until
`cloud_sync` lands with its own (different) path scheme. Harmless to
leave; delete by hand if reclaiming the space matters before then.

**Known limitation (single operator, trusted LAN):** `docker-socket-proxy`'s
grant has no per-container ACL — it can start/stop any container on
that host, not just ones with a matching `stop-during-backup` label. The
label match on the `docker-volume-backup` side is what actually scopes
each schedule to its own app (see Architecture above); the proxy itself
is a broader grant than that.

## S3 endpoint format

`offsite_backup_s3_endpoint` (`group_vars/all/main.yaml`) must be a
**bare hostname** (e.g. `s3.store.{{ lab_domain }}`), not a URL —
`docker-volume-backup` passes it straight into minio-go's
`AWS_ENDPOINT`, which rejects a scheme prefix (`Endpoint url cannot
have fully qualified paths`). Scheme
is the separate `.proto` key on each target (default `https`).

## Restore

`playbooks/restore.yaml` wraps `ansible/roles/restore`: extracts a
decrypted archive into one or more named volumes, stopping and
redeploying the app's compose stack around it. It's a single play
(`hosts: managed_hosts`, validation `delegate_to: localhost` inline) —
splitting validation into a separate controller-only play silently skips
it under `--limit <group>`. For the same reason it can't
`import_playbook` the secrets bootstrap; pass it as a separate file on
the command line instead (see below).

Two gates block the destructive steps, each covered by a
[Molecule scenario](molecule-testing.md) asserting the actual side effect
(container `StartedAt`, volume content), not just exit code:

- **Required vars** — `restore_app`, `restore_archive_local_path`,
  `restore_volumes`, and the archive existing on the controller.
- **Human confirmation** — a `pause` prompt. `restore_confirm` is a
  three-state signal (undefined → real prompt; `true`/`false` → `-e`-only,
  deterministic) so automated runs without a tty fail closed by default.

```sh
ansible-playbook playbooks/bootstrap-secrets.yaml playbooks/restore.yaml \
  -i inventory/inventory.yaml --limit services,localhost \
  -e restore_app=kms \
  -e restore_archive_local_path=/home/you/services-kms-r2-2026-07-29T04-00-00.tar.gz \
  -e restore_volumes='["kms_data"]'
```

Each archive holds exactly one app (one schedule = one app × one cloud
target — see Architecture above), so `restore_volumes` only ever needs
to list that one app's own volumes.

Manual steps before running it (private key never touches a homelab host):

1. Pull the object from the `homelab-backups` bucket (filer UI, or an S3
   client against `https://s3.store.{{ lab_domain }}`).
2. `gpg --decrypt` it into a plain `.tar.gz`.
3. Point `restore_archive_local_path` at that file.

The playbook copies the archive to the target host, stops the app, extracts
into a scratch volume, matches each name in `restore_volumes` against the
archive's directory structure, copies it over the live volume, cleans up,
and redeploys. It pauses for `yes` before touching anything.

For `lldap` (multiple volumes in one archive):

```sh
-e restore_volumes='["lldap_data","lldap_certs","lldap_creds","lldap_letsencrypt_conf","lldap_letsencrypt_lib"]'
```

For `minecraft`, restoring `minecraft_backups` only gets you the on-host
`mc-backup` tar window — unpacking the newest tar into `minecraft_data`
needs `itzg/mc-backup`'s `restore-tar-backup` entrypoint as a second
step, deliberately kept out of Ansible:
`docker/minecraft/scripts/run_restore.sh` (deployed alongside the app,
see `app_registry.yaml`), runs directly on the `play` host. For the
common case — undoing today's session from last night's on-host
snapshot — that script alone is the whole restore, no offsite archive
or the `restore` role involved at all. Run it after this playbook only
when `minecraft_backups` itself needed reconstituting first (host disk
loss). See the script's own header for both usages.

## Out of scope

- Off-site/cloud replication of the `storage` host's own SeaweedFS data
  store — R2/B2/OCI hold independent app-level archives, not a mirror of
  SeaweedFS's bucket.
- HA for SeaweedFS (single-node by design).
- Alerting on silent backup-job failures.
