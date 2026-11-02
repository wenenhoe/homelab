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
| 6 | Dump the stopped VM and destroy it, then delete its Kea reservation and lease on the live gateway | [the cycle](../../projects/tofu-migration.md#stage-2--cutover) | no |
| 7 | Declare the VM, apply, run the inventory generator | [`vm-provisioning.md`](../infra/vm-provisioning.md#tofu--ansible-handoff) | yes |
| 8 | Remove the old SSH host key from `known_hosts` for the host's name and address | `ssh-keygen -R` | no |
| 9 | Deploy | `deploy.yaml --limit <host>,localhost`; `security` first needs [the bootstrap](../secrets/openbao-backup-restore.md#rebuilding-security) | yes |
| 10 | Restore the host's apps | `python3 ansible/scripts/restore_all.py --host <host>` (`--skip step-ca` on `security`) | yes |
| 11 | Set the host's new Beszel agent fingerprint in the hub | [`beszel.md`](../monitoring/beszel.md#rebuilding-a-host) | no |
| 12 | Check the host | `cd tools && python3 -m rebuild_check.host <host>` | yes |
| 13 | Record the restore in the fire drill, then delete the dump and `fstrim` the pool | [`fire-drill.md`](fire-drill.md#results) | no |

Steps 1 to 5 change nothing on the host being rebuilt, so run them first and stop
if one fails.

## What the scripts check

**Before (`restore_all.py --check`).** Lists the newest backup of each app on
every source that could restore it, with its age, and downloads nothing. It exits
non-zero when an app has no source within 30 hours (`--max-age-hours`), which is
one nightly run and some slack. A source that is unreachable or empty is shown as
such, since the restore falls back from SeaweedFS to the app's cloud targets.

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
- `known_hosts`, the Beszel fingerprint, and the dump, destroy and `fstrim` on
  the node.
- OpenBao's unseal after any restart of it.
- `r2-read-watcher` on `security`. It is installed by hand
  ([`openbao-r2-read-watcher.md`](../secrets/openbao-r2-read-watcher.md#installing)),
  because its AppRole's `role_id` and `secret_id` can be read and minted only by
  the `vault-bootstrap` identity, never by the `controller` identity Ansible runs
  as. `rebuild_check.host security` fails until it is installed.
- Fetching and decrypting the step-ca archive for the `security` bootstrap, which
  is needed before any secret is reachable.
