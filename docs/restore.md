# Restore: Recovering from a Backup

For the backup design this restores from — threat model, encryption,
what's covered — see [`disaster-recovery.md`](disaster-recovery.md).

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
  -e restore_archive_local_path=/home/you/services-kms-2026-07-29T04-00-00.tar.gz \
  -e restore_volumes='["kms_data"]'
```

Each archive holds exactly one app (one schedule = one app — see
[Architecture in `disaster-recovery.md`](disaster-recovery.md#architecture)),
so `restore_volumes` only ever needs to list that one app's own volumes.

Manual steps before running it (private key never touches a homelab host):

1. Pull the object from the `homelab-backups` bucket — normally
   SeaweedFS (filer UI, or an S3 client against
   `https://s3.store.{{ lab_domain }}`). If `storage` itself is what's
   lost — the actual scenario `cloud_sync` exists for — pull the same
   object from whichever of R2/B2/OCI has it instead (each provider's
   own console/CLI; `cloud_sync_targets` in `host_vars/storage.yaml`
   has the bucket name for each, though that file is naturally also
   gone if `storage` is what you lost — keep a copy of which
   bucket/region each provider uses somewhere that survives a
   `storage`-host loss). Same encrypted object either way — `cloud_sync`
   copies it verbatim, nothing about it changes in transit.
2. `gpg --decrypt` it into a plain `.tar.gz`.
3. Point `restore_archive_local_path` at that file.

The playbook then runs through the restore itself in order:

1. Copies the archive to the target host.
2. Stops the app.
3. Extracts into a scratch volume.
4. Matches each name in `restore_volumes` against the archive's
   directory structure.
5. Copies it over the live volume.
6. Cleans up and redeploys.

It pauses for `yes` before touching anything.

For `lldap` (multiple volumes in one archive):

```sh
-e restore_volumes='["lldap_data","lldap_certs"]'
```

## Batch restore (all apps, disaster-recovery scenario)

The above is the per-app runbook — the tested primitive underneath, and
still exactly what a single-app restore should use. `ansible/restore_all.py`
is a thin orchestrator on top of it, for the "lost `services`/`security`/`play`
outright" scenario: it discovers each in-scope app's latest backup itself
(SeaweedFS first, falling back to that app's own cloud target(s) if
SeaweedFS is unreachable), decrypts it, then calls the exact same
`restore.yaml`/`restore` role above once per app, in order. It never
bypasses the per-app gates described above — every call it makes still
goes through the real playbook, confirmation included (see below).

In scope: every app with a `backup:` key in `app_registry.yaml` — the
same test `backup_agent` itself uses to decide what it backs up, so
there's no separate list to keep in sync. That now includes
`uptime-kuma` along with `step-ca`, `kms`, `wastebin`, `beszel-hub`,
`tinyauth`, `lldap`, and `minecraft`. To exclude an app you back up but
never want auto-restored in a batch run, add it to
`restore_discovery_excluded_apps` in
`ansible/roles/restore_discovery/defaults/main.yaml` (empty by
default). step-ca is always ordered first when it's in scope — see
step 4 below for why.

```sh
python3 ansible/restore_all.py            # interactive: one batch summary, one 'yes'
python3 ansible/restore_all.py --yes      # unattended (fire-drill automation, etc.)
```

Run this on the controller only — same machine/trust requirement as
everything else in [`disaster-recovery.md`'s Threat model](disaster-recovery.md#threat-model):
the GPG private key has to be there, and decryption has to be able to
happen non-interactively (gpg-agent already unlocked, or a
passphrase-less key) since nothing here ever prompts for a GPG
passphrase itself.

What it does, in order:

1. Renders a controller-local manifest + a read-only `rclone.conf`
   (`ansible/roles/restore_discovery`, via
   `playbooks/restore-discovery-setup.yaml`) — app → host → volumes →
   cloud fallback target(s), the same `app_registry`/`host_vars`
   resolution `cloud_sync` already does for its own upload side, so the
   two can't drift apart. The rclone identities are the SeaweedFS
   `cloud-sync-reader` identity and the six cloud **read**-leg
   credentials from `docs/cloud-credential-creation.md` — nothing here
   can write to SeaweedFS or any cloud target.
2. For each in-scope app: lists `seaweedfs:homelab-backups/<host>-<app>/`
   (the exact `AWS_S3_PATH` prefix `backup_agent`'s own
   `schedule.env.j2` uses). If that fails outright (SeaweedFS/`storage`
   unreachable), falls back to that app's own cloud target(s) — the
   same `extra_cloud_targets`/`cloud_sync_default_targets` resolution
   `cloud_sync` uses, so a fallback only ever tries a bucket the app
   was actually relayed to. Whichever remote answers, it picks the
   newest object by `BACKUP_FILENAME`'s embedded timestamp (not
   directory-listing order or upload mtime), downloads it, and
   `gpg --decrypt`s it.
3. Prints one batch summary — app / host / source (`seaweedfs` or the
   cloud target name) / object key / timestamp — for every app it
   could discover, and lists anything it couldn't. Asks for a single
   `yes` (skipped with `--yes`). Nothing destructive has happened yet
   at this point.
4. Restores `step-ca` first via the real `restore.yaml`
   (`restore_confirm=true`, since the batch-level confirmation above
   already covers it) — `lldap`/`tinyauth` read its root cert on
   deploy (`deploy.yaml` Play 6), so a step-ca restore (or discovery)
   failure aborts the whole batch before touching anything else.
5. Restores the remaining apps, each via the same `restore.yaml` call.
   `minecraft` gets a second step afterward —
   `playbooks/restore-minecraft-world.yaml`, which runs
   `docker/minecraft/scripts/run_restore.sh -y` on `play` (see below).
   A failure in any one of these is independent and doesn't block the
   rest; only step-ca's failure aborts everything.
6. Appends one line per app to
   `ansible/files/restore/audit-log.jsonl` (git-ignored, same as
   `ansible/files/secrets/`) — object key, timestamp, and outcome —
   and deletes the decrypted plaintext from its own scratch directory
   once that app's `restore.yaml` call has finished, success or not.

**Known limitation carried over, not introduced here:** `minecraft`'s
own backup uses `compression: none`
([`disaster-recovery.md`](disaster-recovery.md#whats-backed-up)) — the
`restore` role's own extraction step assumes gzip (`tar -xzf`)
unconditionally, and hasn't been re-verified against an uncompressed
archive. That's the existing, tested `restore` role's own behavior,
unchanged here; if a real `minecraft` restore hits it, that's a
`restore` role fix, not something `restore_all.py` should work around.

**Needs live verification, not yet confirmed against a real endpoint:**
whether `rclone lsjson` against a prefix with zero objects (bucket
reachable, nothing backed up there yet) and against a genuinely
unreachable endpoint are actually distinguishable by exit code the way
`restore_all.py` assumes (nonzero exit → try the cloud fallback; zero
exit + empty list → hard "no objects found" instead, so a real
connectivity problem is never mistaken for "this app was just never
backed up"). Check directly before relying on this in a real outage:

```sh
rclone lsjson --config ansible/files/restore/rclone.conf \
  seaweedfs:homelab-backups/<host>-<app>
```

Also unverified: `rclone copyto`'s 20-second IO-idle timeout (not a
total-transfer cap — set in `_run_rclone`, `ansible/restore_all.py`)
could mistake a brief-but-legitimate stall on a slow or high-latency
link for a stuck download, on a large archive over a weak connection.
Worth watching for on the first real restore over anything other than
a fast LAN link.

For a fire drill proving the whole path end to end against real
infrastructure, see [`fire-drill.md`](fire-drill.md).

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
