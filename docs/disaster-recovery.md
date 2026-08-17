# Disaster Recovery — Off-host and Cloud Backups

A separate VM (`storage`, `192.168.20.6`) runs
[SeaweedFS](https://github.com/seaweedfs/seaweedfs) as a self-hosted
S3-compatible target. One [`offen/docker-volume-backup`](https://github.com/offen/docker-volume-backup)
agent per host (`backup_agent` role) pushes GPG-encrypted archives of
selected named volumes to SeaweedFS and, per-app, to one or more of
Cloudflare R2 / Backblaze B2 / OCI Object Storage — see "What's backed
up" below.

S3 credential generation/rotation is covered in [`secrets.md`](secrets.md),
not here.

## Architecture

- Volumes to back up are declared per-app via a `backup:` key on the app's
  `app_registry` entry — the agent has no per-app logic beyond that.
- One `docker-volume-backup` container per host runs one schedule per
  (app, cloud target) pair — e.g. an app backed up to both SeaweedFS and
  R2 gets two independent schedules, each producing its own archive with
  its own retention/cron. `docker-volume-backup` does full tar-and-upload
  per run, no delta sync — a schedule's cost scales with that one app's
  volume size, not with anything else sharing the container.
- Apps that need to be stopped for a consistent snapshot set
  `docker-volume-backup.stop-during-backup=<app-name>` on their own
  compose service (their own name, not a shared `true`) and
  `backup.stop_during_backup: true` in `app_registry.yaml`. Each of that
  app's schedules then sets `BACKUP_STOP_DURING_BACKUP_LABEL=<app-name>`
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

| Host | App → volumes | Stopped during backup | Cloud targets | Retention |
| :--- | :--- | :--- | :--- | :--- |
| `services` | `kms` → `data` | yes (`kms`) | SeaweedFS, R2, B2 | 7 days |
| `services` | `wastebin` → `data` | no | SeaweedFS, R2, B2 | 7 days |
| `security` | `beszel-hub` → `data` | yes (`beszel-hub`) | SeaweedFS, R2, B2 | 7 days |
| `security` | `tinyauth` → `data` | yes (`tinyauth`) | SeaweedFS, R2, B2 | 7 days |
| `security` | `lldap` → `data`, `certs` | no | SeaweedFS, R2, B2 | 7 days |
| `play` | `minecraft` → `backups` only | no | SeaweedFS, OCI | 7 days |

Apps without a `backup:` key in `app_registry.yaml` are out of scope.

`lldap` is deliberately never stopped — it's the auth backend, and every
other app behind Caddy/tinyauth loses login for the stop window, a
bigger blast radius than the SQLite-consistency risk it'd guard against.
`minecraft`'s `backups` volume is already RCON-quiesced by `itzg/mc-backup`
before this ever reads it (`docker/minecraft/compose.yaml`), so stopping
`mc` here would add downtime with no consistency benefit. If a restore
ever turns up a corrupt SQLite/LDAP file for `wastebin`/`lldap`, add
`stop_during_backup: true` and the matching compose label (see
Architecture above) rather than assuming it's needed by default.

**Cloud target selection:** every app's `cloud_targets` defaults to
`cloud_backup_default_targets` (`group_vars/all/main.yaml`) — currently
`[seaweedfs, r2, b2]`. `minecraft` overrides to `[seaweedfs, oci]`: its
~1.8GB/night archive at 7-day retention (~13GB) would eat most of a
single 10GB R2/B2 free tier, so it gets OCI's 20GB allowance to itself
instead. See `cloud_backup_targets` (same file) for each provider's
bucket/endpoint.

**Before first use of R2/B2/OCI:**

- Create a `homelab-backups` bucket by hand on each (not Ansible-managed,
  same as the note in "Bucket creation" above for SeaweedFS being the
  one exception) — a reasonable first OpenTofu project once that
  expansion starts.
- Fill in the six `cloudflare-r2-*`/`backblaze-b2-*`/`oci-*` entries in
  `secrets_registry.yaml` via `bootstrap_secrets.py` — see
  [`secrets.md`](secrets.md). Scope each credential to just that bucket.
- `cloud_backup_targets.b2.endpoint` is a guess
  (`s3.us-west-004.backblazeb2.com`) — B2 assigns your bucket's actual
  region at creation. Confirm it in the B2 console (Bucket Details)
  before deploying, or that schedule fails closed (wrong endpoint →
  auth/DNS error, not a silent skip).
- Confirm path-style addressing actually works against each real bucket
  (`aws s3 ls --endpoint-url ... s3://homelab-backups` or `mc ls`) before
  trusting the nightly run — `AWS_S3_FORCE_PATH_STYLE=true` is a
  reasonable default here (all three document support for it) but isn't
  verified against your specific tenancy/bucket.

**Migration note:** archives now key on the app's own name
(`AWS_S3_PATH`/`BACKUP_FILENAME`, e.g. `services-kms-r2`), not a shared
`stop-group`/`no-stop-group` prefix bundling several apps into one
archive. Existing SeaweedFS objects under the old prefixes are orphaned
by this — no longer retention-pruned, they just sit there. Harmless;
delete by hand once the new per-app archives have run successfully a
few times, if reclaiming the space matters.

**Known limitation (single operator, trusted LAN):** `docker-socket-proxy`'s
grant has no per-container ACL — it can start/stop any container on
that host, not just ones with a matching `stop-during-backup` label. The
label match on the `docker-volume-backup` side is what actually scopes
each schedule to its own app (see Architecture above); the proxy itself
is a broader grant than that.

## S3 endpoint format

Every `cloud_backup_targets.*.endpoint` (`group_vars/all/main.yaml`,
SeaweedFS included) must be a **bare hostname**
(e.g. `s3.store.{{ lab_domain }}`), not a URL — `docker-volume-backup`
passes it straight into minio-go's `AWS_ENDPOINT`, which rejects a
scheme prefix (`Endpoint url cannot have fully qualified paths`). Scheme
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
