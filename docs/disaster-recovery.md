# Disaster Recovery — Stage 1: Off-host Backups

Stage 1 of a staged DR plan: a separate VM (`storage`, `192.168.20.6`) runs
[SeaweedFS](https://github.com/seaweedfs/seaweedfs) as a self-hosted
S3-compatible target. One [`offen/docker-volume-backup`](https://github.com/offen/docker-volume-backup)
agent per host (`backup_agent` role) pushes GPG-encrypted archives of
selected named volumes to it nightly. No off-site/cloud copy yet (stage 2).

S3 credential generation/rotation is covered in [`secrets.md`](secrets.md),
not here.

## Architecture

- Volumes to back up are declared per-app via a `backup:` key on the app's
  `app_registry` entry — the agent has no per-app logic beyond that.
- `docker-volume-backup` does full tar-and-upload per run, no delta sync, so
  apps are grouped by matching retention/schedule, not by convenience.
- Each host runs **at most two** `backup_agent` instances, split by
  `backup.stop_during_backup`:
  - **stop-during-backup group** — shares one `docker-socket-proxy`
    (`CONTAINERS=1 POST=1 INFO=1`), one archive, one schedule. Containers are
    stopped/restarted together for one consistent snapshot.
  - **no-stop group** — backed up live, no proxy needed.
- `backup_agent`'s `compose.yaml` is rendered from a Jinja template (the only
  templated compose file in this repo) since mounted volumes vary per host.
- Conflicting `retention_days`/`cron` within a group is a hard failure, not
  a silent pick — see `ansible/roles/backup_agent/tasks/main.yaml`.

## Storage host

SeaweedFS runs single-node (`weed server -filer -s3`) — sufficient for "a
copy exists off-host," not HA for the backup target itself.

- **Filer web UI** (`https://filer.store.{{ lab_domain }}`) — human-facing,
  Caddy + Tinyauth + TLS like every other app.
- **S3 API** (`https://s3.store.{{ lab_domain }}`) — machine-facing only.
  Registered `auth: false` (Tinyauth's forward-auth needs an interactive
  redirect a non-interactive S3 client can't complete). Auth is instead the
  S3 SigV4 keypair in `docker/seaweedfs/configs/s3-identity.json.j2`, scoped
  to only the `homelab-backups` bucket. See the [SeaweedFS S3 Configuration
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

| Host | Group | Apps → volumes | Retention |
| :--- | :--- | :--- | :--- |
| `services` | stop-during-backup | `kms` → `data` | 7 days |
| `services` | no-stop | `wastebin` → `data` | 7 days |
| `security` | stop-during-backup | `beszel-hub` → `data`, `tinyauth` → `data` | 7 days |
| `security` | no-stop | `lldap` → `data`, `certs`, `creds`, `letsencrypt_conf`, `letsencrypt_lib` | 7 days |
| `play` | no-stop | `minecraft` → `backups` only | 7 days |

Apps without a `backup:` key in `app_registry.yaml` are out of scope for
stage 1.

**Known limitations (single operator, trusted LAN):**

- `docker-socket-proxy`'s grant has no per-container ACL — it can
  start/stop any container on that host, not just its group.
- Grouping couples downtime: apps sharing an archive are stopped for the
  full run, not just their own volume's slice.

`lldap` and `wastebin` are backed up live. If a restore ever turns up a
corrupt SQLite/LDAP file, add `stop_during_backup: true` to that app.

## S3 endpoint format

`offsite_backup_s3_endpoint` (`group_vars/all/main.yaml`) must be a **bare
hostname** (`s3.store.{{ lab_domain }}`), not a URL — `docker-volume-backup`
passes it straight into minio-go's `AWS_ENDPOINT`, which rejects a
scheme prefix (`Endpoint url cannot have fully qualified paths`). The
scheme is the separate `offsite_backup_s3_proto` var (default `https`).

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
  -e restore_archive_local_path=/home/you/services-stop-group-2026-07-29T04-00-00.tar.gz \
  -e restore_volumes='["kms_data"]'
```

A shared archive can hold more than one app's volumes (e.g. `security`'s
stop-group archive has both `beszel-hub_data` and `tinyauth_data`) —
`restore_volumes` only needs to list what you're restoring.

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
needs `itzg/mc-backup`'s `restore-tar-backup` entrypoint as a second step
(`docker/minecraft/compose.restore.yaml`).

## Out of scope for stage 1

- Off-site/cloud replication of the `storage` host itself.
- HA for SeaweedFS (single-node by design).
- Alerting on silent backup-job failures.
