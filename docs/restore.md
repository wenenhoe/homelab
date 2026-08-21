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
