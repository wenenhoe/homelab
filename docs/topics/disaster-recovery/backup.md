# Backup — Off-host and Cloud Copies

A separate VM (`storage`) runs
[SeaweedFS](https://github.com/seaweedfs/seaweedfs) as a self-hosted
S3-compatible target. One [`offen/docker-volume-backup`](https://github.com/offen/docker-volume-backup)
agent per host (`backup_agent` role) pushes GPG-encrypted archives of
selected named volumes to SeaweedFS — nothing else. Cloud coverage
(Cloudflare R2 / Backblaze B2 / OCI Object Storage) is a separate
`cloud_sync` role running only on `storage`, reading those same
already-encrypted objects out of SeaweedFS and copying them onward — see
[`backup-threat-model.md`](backup-threat-model.md) for why it's designed this way, "What's backed up"
for SeaweedFS coverage, and [`cloud-sync.md`](cloud-sync.md) for how the
cloud leaf works.

S3 credential generation/rotation is covered in [`secrets.md`](../secrets/secrets.md),
not here.

OpenBao's own backup/restore uses a different mechanism entirely (a
raft snapshot, not this volume-backup pipeline) — see
[`openbao-backup-restore.md`](../secrets/openbao-backup-restore.md).

Getting data back is [`restore.md`](restore.md); proving that path works end
to end is [`fire-drill.md`](fire-drill.md).

## Architecture

- Volumes to back up are declared per-app via a `backup:` key on the app's
  `app_catalog` entry — the agent has no per-app logic beyond that.
- One `docker-volume-backup` container per host runs one schedule per
  app, always to SeaweedFS. `docker-volume-backup` does full
  tar-and-upload per run, no delta sync — a schedule's cost scales with
  that one app's volume size, not with anything else sharing the
  container.
- Apps that need to be stopped for a consistent snapshot set
  `docker-volume-backup.stop-during-backup=<app-name>` on their own
  compose service (their own name, not a shared `true`) and
  `backup.stop_during_backup: true` in `app_catalog.yaml`. Each such
  app's schedule then sets `BACKUP_STOP_DURING_BACKUP_LABEL=<app-name>`
  to match. That match is scoped per schedule file, not once for the
  whole container: a schedule backing up app A never touches app B's
  uptime, even though every app's schedules share one container.
  The agent reaches the Docker API through a `docker-socket-proxy` sidecar,
  which is only added to the compose file at all if at least one app on the
  host needs stopping. The sidecar runs the stock image with no capability
  flags: the role's `docker-api-rules.cfg` is mounted read-only over the
  image's `haproxy.cfg.template` and names the calls the agent makes. It
  passes `GET` of `/_ping`, `/version`, `/info` and `/containers/json`, and a
  `POST` to `/containers/{id}/start` or `/stop` for a full 64-character
  lower-case id, with or without an API version prefix, and refuses every
  other call with a 403. Editing the file recreates the container, through a
  label that carries its hash. See
  [ADR 0004 (Docker API access)](../../decisions/0004-container-access-to-the-docker-api/revision-001.md)
  for why anything needing Docker API access gets a scoped proxy sidecar
  like this instead of the real socket, and for the calls.
- `backup_agent`'s `compose.yaml` is rendered from a Jinja template (the
  only templated compose file in this repo) since mounted volumes vary
  per host.
- The container runs as root with every capability dropped except
  `DAC_READ_SEARCH`, and `no-new-privileges` set. Every volume is mounted
  read-only, so it only ever reads: the capability lets it open the schedule
  files the deploy user owns and the files each app's own user owns, and
  `DAC_OVERRIDE` is not needed. The `docker-socket-proxy` sidecar drops every
  capability as well and adds none back, and sets `no-new-privileges`. See
  [Container hardening](../deploy/adding-an-app.md#container-hardening).
- No retention/cron conflict validation is needed — every schedule is
  independent, so there's nothing to conflict.

## Storage host

SeaweedFS runs single-node (`weed server -filer -s3`) — sufficient for "a
copy exists off-host," not HA for the backup target itself.

- **Filer web UI** (`https://filer.store.{{ lan_domain }}`) — human-facing,
  Caddy + Tinyauth + TLS like every other app, and read-only: the route
  registers `read_only: true`, so Caddy answers anything but `GET` and
  `HEAD` with 405. Writes and deletes go through the S3 API's scoped
  identities only.
- **S3 API** (`https://s3.store.{{ lan_domain }}`) — machine-facing only.
  Registered `auth: false` (Tinyauth's forward-auth needs an interactive
  redirect a non-interactive S3 client can't complete). Auth is instead
  the per-identity S3 SigV4 keypairs in
  `docker/seaweedfs/configs/s3-identity.json.j2` — one broad
  bucket-admin identity (bucket creation only), one narrow, path-scoped
  identity per `backup_agent` host, and one bucket-wide but read-only
  identity for `cloud_sync`'s own relay-outward reads. See
  [`backup-threat-model.md`](backup-threat-model.md) for why, and the [SeaweedFS S3 Configuration
  wiki](https://github.com/seaweedfs/seaweedfs/wiki/S3-Configuration) to
  adjust the scoping.

## Bucket creation

SeaweedFS does not auto-create a bucket on first `PUT`, even with
`Admin`-scoped credentials. `ansible/roles/seaweedfs_bucket` creates it
explicitly (Play 5 in `deploy.yaml`, `storage` only, after SeaweedFS
deploys and before `backup_agent` runs). Kept out of `backup_agent` itself
since bucket creation is a one-time storage-side concern.

The role leaves the bucket's versioning suspended. Each agent prunes by
retention (see "What's backed up") with a plain delete, which on a versioned
bucket only adds a delete marker and keeps the archive stored; suspended, the
delete frees the data. A pruned archive still leaves a zero-byte delete marker.

## Encryption

Archives are GPG-encrypted (`GPG_PUBLIC_KEY_RING_FILE`) with an asymmetric
keypair: hosts hold only the public key; the private key stays offline and
is never on any homelab host, so a compromised host can't decrypt existing
backups.

`ansible/files/backup-gpg-public-key.asc` is the public half of the live
backup key. Show its fingerprint with:

```sh
gpg --show-keys --with-fingerprint ansible/files/backup-gpg-public-key.asc
```

Replacing the file only affects archives written afterwards: every archive
already in SeaweedFS or a cloud target stays encrypted to the old key, so
the old private key has to be kept for as long as any of them is
retained.

### Generating a keypair

Only needed for a first deploy or to rotate the key.

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

| Host | App → volumes | Stopped during backup | Retention | Cloud targets |
| :--- | :--- | :--- | :--- | :--- |
| `services` | `kms` → `data` | yes (`kms`) | 7 days | R2, B2 (default) |
| `services` | `wastebin` → `data` | no | 7 days | R2, B2 (default) |
| `security` | `beszel-hub` → `data` | yes (`beszel-hub`) | 7 days | R2, B2 (default) |
| `security` | `tinyauth` → `data` | yes (`tinyauth`) | 7 days | R2, B2 (default) |
| `security` | `lldap` → `data`, `certs` | no | 7 days | R2, B2 (default) |
| `security` | `step-ca` → `data` | no | 7 days | R2, B2 (default) |
| `play` | `minecraft` → `backups` only | no | 7 days | OCI (override) |

Apps without a `backup:` key in `app_catalog.yaml` are out of scope.
Every app above lands in SeaweedFS directly (`backup_agent`, per-host,
nightly); "Cloud targets" is what `cloud_sync` (storage-only, see
[`cloud-sync.md`](cloud-sync.md)) additionally relays it to, on its own
separate schedule. A failed run alerts to Telegram — see
[`telegram-notifications.md`](../monitoring/telegram-notifications.md).

Schedule, retention, compression and whether the app is stopped come from
`backup_defaults` (`group_vars/all/main.yaml`) unless the app's own
`backup:` block sets them; see
[`adding-an-app.md`](../deploy/adding-an-app.md#2-register-it-in-app_catalog).

`lldap` is deliberately never stopped — it's the auth backend, and every
other app behind Caddy/tinyauth loses login for the stop window, a
bigger blast radius than the SQLite-consistency risk it'd guard against.
`minecraft`'s `backups` volume is already RCON-quiesced by `itzg/mc-backup`
before this ever reads it (`docker/minecraft/compose.yaml.j2`), so stopping
`mc` here would add downtime with no consistency benefit. If a restore
ever turns up a corrupt SQLite/LDAP file for `wastebin`/`lldap`, add
`stop_during_backup: true` and the matching compose label (see
Architecture above) rather than assuming it's needed by default.

For the same reason, `minecraft` also sets `backup.compression: none` —
`itzg/mc-backup` already gzips the archive `backup_agent` mounts, so
`backup_agent`'s own default `gz` pass would just be re-compressing an
already-compressed file for no size benefit. Every other app above uses
the `gz` default since their sources are raw, uncompressed volume data.

**Migration note:** every app host previously also pushed directly to
R2/B2/OCI (a design [the threat model](backup-threat-model.md) rules out). Any
objects already sitting in those buckets from that period are now
orphaned under a different path scheme than `cloud_sync` uses — nothing
will prune them, and `cloud_sync` won't add to or recognize them.
Harmless to leave; delete by hand if reclaiming the space matters.

**Known limitation (single operator, trusted LAN):** `docker-socket-proxy`'s
grant has no per-container ACL — it can start/stop any container on
that host by id, and list every container with its labels, not just ones
with a matching `stop-during-backup` label. The label match on the
`docker-volume-backup` side is what actually scopes each schedule to its own
app (see Architecture above); the proxy itself is a broader grant than that.
It cannot create, exec into, kill, update or delete a container, read a
container's environment, files or logs, or reach any other endpoint.

## Running a backup now

Only the nightly schedule starts a backup. To take one outside it, run
`backup` inside the agent container with one app's schedule file as the
environment, as the deploy user on that app's host, from the
`backup-agent` directory under `compose_deploy_dir`:

```sh
docker exec --env-file conf.d/<app>.env backup-agent backup
```

One schedule file is one app and one archive. To back up every app on the
host, stopping at the first failure:

```sh
for f in conf.d/*.env; do docker exec --env-file "$f" backup-agent backup || break; done
```

The environment has to come from `--env-file`. The container's own
environment holds only the settings shared by every schedule (`.env`), so
a bare `docker exec backup-agent backup` has no bucket and no
`BACKUP_FILENAME`: it archives `/backup`, every app's volumes in one
archive, and uploads nothing. Sourcing the file in the container's shell,
as the upstream docs describe, fails on the `{{ .Extension }}` in
`BACKUP_FILENAME`; the variable stays unset and the archive is named
`backup-<timestamp>`, which restore discovery does not recognise (it
matches `<host>-<app>-<timestamp>`). `--env-file` passes every setting
through unchanged.

- **Exit status.** The command exits non-zero when the archive is not
  created or not uploaded, and a failure alerts to Telegram like a
  scheduled run does.
- **Stopped apps.** An app marked "Stopped during backup" above is stopped
  for the run, as it is overnight.
- **Overlap.** A run that meets a running one waits for the container's
  lock, up to the agent's lock timeout (60 minutes by default), instead
  of running alongside it.
- **Pruning.** Every run also prunes archives past the app's retention.

Exit status 0 means the upload finished. To see the object, list the
host's `<host>-<app>/` prefix in the bucket, for example in the filer web
UI; the newest object is the one just taken. The freshness check cannot
confirm it, since its threshold is the app's cron period plus a buffer,
which the previous night's archive already satisfies.

The cloud copies follow on `cloud_sync`'s own schedule. To relay now, on
`storage`:

```sh
sudo systemctl start cloud-sync.service
```

The unit is a oneshot, so the command returns when the run ends and fails
if any job failed; the jobs' output is in `journalctl -u cloud-sync.service`.

OpenBao is not in this pipeline. Its snapshot is taken as
[`openbao-backup-restore.md`](../secrets/openbao-backup-restore.md#running-a-backup)
describes.

## S3 endpoint format

`seaweedfs_s3_endpoint` (`group_vars/all/main.yaml`) must be a
**bare hostname** (e.g. `s3.store.{{ lan_domain }}`), not a URL —
`docker-volume-backup` passes it straight into minio-go's
`AWS_ENDPOINT`, which rejects a scheme prefix (`Endpoint url cannot
have fully qualified paths`). Scheme is the separate
`seaweedfs_s3_proto` var (default `https`). `cloud_sync`'s own
`rclone.conf` is unrelated and follows the opposite convention — see
[`cloud-sync.md`](cloud-sync.md).

## Out of scope

- Off-site/cloud replication of the `storage` host's own SeaweedFS data
  store — R2/B2/OCI hold independent app-level archives, not a mirror of
  SeaweedFS's bucket.
- HA for SeaweedFS (single-node by design).
