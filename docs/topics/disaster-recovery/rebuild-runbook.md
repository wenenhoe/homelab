# Rebuilding a host

How a Tofu-built Ubuntu host is destroyed and rebuilt from the repository and its
backups, what each step is run with, and what is still done by hand. The
execution record of the migration that rebuilds the five Ubuntu hosts is
[`tofu-migration.md`](../../projects/tofu-migration.md); this is the procedure.
The backup and restore mechanics are in [`backup.md`](backup.md) and
[`restore.md`](restore.md), and what a restore proved is in
[`fire-drill.md`](fire-drill.md#results).

## Order of a rebuild

| # | Step | Run with | Scripted |
| :-: | :--- | :--- | :-: |
| 1 | Every app of the host has a recent backup on some source | `python3 ansible/scripts/restore_all.py --check --host <host>` | yes |
| 2 | Take an on-demand backup of the host's apps and confirm each archive is in SeaweedFS | [`backup.md`](backup.md#running-a-backup-now) | partly |
| 3 | `security` only: take the OpenBao snapshot | `tools/openbao_utils/scripts/snapshot-push.sh <role_id>` | yes |
| 4 | Copy Tofu's state | `tofu state pull` | yes |
| 5 | Prepare and stage the Ubuntu image if the pin or `timezone` changed | [`prepare_image.sh`](../infra/vm-provisioning.md#prepared-ubuntu-image), then `scp` to the node | partly |
| 6 | Dump the stopped VM and destroy it, then delete its Kea reservation and lease on the live gateway | [`retire_vm.sh`](#on-the-node) `dump` and `destroy`; the reservation by hand ([the cycle](../../projects/tofu-migration.md#stage-2--cutover)) | partly |
| 7 | Declare the VM, apply, run the inventory generator | [`vm-provisioning.md`](../infra/vm-provisioning.md#tofu--ansible-handoff) | yes |
| 8 | Remove the old SSH host key from `known_hosts` for the host's name and address | `cd tools && python3 -m rebuild_check.known_hosts <host>` | yes |
| 9 | Deploy | `deploy.yaml --limit <host>,localhost`; `security` first needs [the bootstrap](../secrets/openbao-backup-restore.md#rebuilding-security) | yes |
| 10 | Restore the host's apps | `python3 ansible/scripts/restore_all.py --host <host>` (`--skip step-ca` on `security`) | yes |
| 11 | Set the host's new Beszel agent fingerprint in the hub | [`beszel.md`](../monitoring/beszel.md#rebuilding-a-host) | no |
| 12 | Check the host, then that both DNS servers agree on it | `cd tools && python3 -m rebuild_check.host <host>`; `python3 -m rebuild_check.dns <host>` | yes |
| 13 | Record the restore in the fire drill, then delete the dump and `fstrim` the pool | [`fire-drill.md`](fire-drill.md#results); [`retire_vm.sh`](#on-the-node) `drop-dump` | partly |

Steps 1 to 5 change nothing on the host being rebuilt, so run them first and stop
if one fails.

## On the node

[`retire_vm.sh`](../../../tools/rebuild_check/scripts/retire_vm.sh) runs on the
Proxmox node as root, piped over SSH, against the dump storage that
[Dump storage](../../projects/tofu-migration.md#dump-storage) creates:

```sh
ssh root@<node> 'bash -s -- dump 204 play' < tools/rebuild_check/scripts/retire_vm.sh
ssh root@<node> 'bash -s -- destroy 204 play' < tools/rebuild_check/scripts/retire_vm.sh
ssh root@<node> 'bash -s -- drop-dump 204' < tools/rebuild_check/scripts/retire_vm.sh
```

The VMID is followed by the VM's name in Proxmox, which has to match, so a
mistyped VMID dumps or destroys nothing. `dump` and `destroy` also refuse a
VM that is not stopped or a dump storage that is not mounted. `dump` refuses a
VM that already has a dump, so the rollback of an earlier rebuild is never
replaced by accident, and fails on a dump that is missing or empty. `destroy`
runs only when exactly one non-empty dump of the VM is there. `drop-dump`
deletes that VM's dump, log and notes and runs `fstrim -v` on the dump volume.
`DUMP_STORAGE` and `DUMP_DIR` name the storage and its mount point, `vzdump` and
`/mnt/vzdump` by default.

The rollback is `qmrestore` of the dump to a 9XX VMID, as the cycle says.

## What the scripts check

**Before (`restore_all.py --check`).** Lists the newest backup of each app on
every source that could restore it, with its age, and downloads nothing. It exits
non-zero when an app has no source within 30 hours (`--max-age-hours`), which is
one nightly run and some slack. A source that is unreachable or empty is shown as
such, since the restore falls back from SeaweedFS to the app's cloud targets. The
MTIME column compares each source's modification time of that archive with the
instant its name stamps; a difference of more than an hour is shown and named in
a warning, and does not change the exit status. It says the archive was copied
without its original time, which the relay's `--max-age` and a bucket's
lifecycle would read as young.

**After (`rebuild_check.host`).** One line per check, over SSH, changing nothing:

| Check | What it catches |
| :--- | :--- |
| `address_is_static` | The address came from a DHCP lease, not cloud-init |
| `no_dracut_network_file` | The initramfs brought the NIC up with DHCP |
| `own_name_resolves_to_its_address` | The host's name resolves to loopback on the host |
| `containers_resolve_the_hosts_name` | A container on `caddy-proxy` resolves the host's name to something else |
| `timezone_is_the_inventorys` | The host is not on `server_timezone` |
| `no_failed_units` | A systemd unit failed |
| `containers_are_running_and_healthy` | A container exited, restarts, is unhealthy or is still starting |

`security` has four more: `openbao_is_unsealed`, `step_ca_is_healthy`,
`tinyauth_reaches_ldap` (no LDAP error lines in tinyauth's last ten minutes) and
`r2_read_watcher_is_running`. A host's address is what the lab's DNS says for its
name, so a wrong record fails the check on the host instead of being trusted.
Add a check for what only another host runs to `HOST_CHECKS` in
[`rebuild_check/host.py`](../../../tools/rebuild_check/host.py).

`containers_resolve_the_hosts_name` is the one `docker ps` cannot stand in for:
tinyauth and lldap were both healthy while tinyauth could not reach lldap.

**DNS (`rebuild_check.dns`).** Asks `services` (primary) and `storage`
(secondary) directly with `dig`, from the machine it runs on, and changes
nothing. The gateway forwards to both, so a server that came back with an older
zone answers some of the lab's queries while the other looks fine.

| Check | What it catches |
| :--- | :--- |
| `zones_have_one_serial` | The host zone or the lan zone has a different SOA serial on the two servers, or a server does not answer or holds no such zone |
| `resolves_alike: <name>` | The two servers give different addresses for a host's name; for a host Tofu built, both give another address than the generated inventory's |

With no host named it covers every host in `managed_hosts` and `network_infra`,
and `s3.store` in the lan zone, which has no expected address and is checked for
agreement only.

## Per host

- **`play` and `security`** are rebuilt. `security` cannot be deployed by
  `deploy.yaml` until OpenBao and step-ca exist on it, which is
  [its own procedure](../secrets/openbao-backup-restore.md#rebuilding-security):
  `predeploy.yaml`, then `bootstrap-security.yaml` in three stages with the
  operator's steps between them, then `deploy.yaml`. Its `restore_all.py` run
  skips `step-ca`, which the bootstrap restored.
- **`storage`** is the exception to the cycle: its SeaweedFS data is in a Docker
  volume on the VM's own disk, so it is built beside the old VM at VMID 207 and
  its buckets are copied across before the old one is destroyed
  ([Moving `storage`](../../projects/tofu-migration.md#moving-storage)).
- **`services`**, **`tailscale`**: not rebuilt yet. Their plan is in
  [`tofu-migration.md`](../../projects/tofu-migration.md#stage-2--cutover), and a
  topic here would describe what has not been done.

## Still done by hand

Not scripted, and where each is described:

- The gateway's Kea reservation and lease, and any alias, rule or forward that
  names the old address ([the cycle](../../projects/tofu-migration.md#stage-2--cutover)).
- The Beszel fingerprint, and creating the dump storage once.
- OpenBao's unseal after any restart of it.
- `r2-read-watcher` on `security`. It is installed by hand
  ([`openbao-r2-read-watcher.md`](../secrets/openbao-r2-read-watcher.md#installing)),
  because its AppRole's `role_id` and `secret_id` can be read and minted only by
  the `vault-bootstrap` identity, never by the `controller` identity Ansible runs
  as. `rebuild_check.host security` fails until it is installed.
- Fetching and decrypting the step-ca archive for the `security` bootstrap, which
  is needed before any secret is reachable.
