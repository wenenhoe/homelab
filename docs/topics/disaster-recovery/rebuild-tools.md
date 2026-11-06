# Rebuild tools

The scripts the [rebuild runbook](rebuild-runbook.md) calls: what each does,
what it refuses, and the dump storage they depend on. They live in
[`tools/rebuild_check/`](../../../tools/rebuild_check/).

| Tool | Runs on | Used at step | Does |
| :--- | :--- | :-: | :--- |
| [`retire_vm.sh`](#retire_vmsh) | The Proxmox node, as root, piped over SSH | 6, 13, rollback | Dumps, destroys and restores a VM; drops its dump |
| [`bucket_copy.py`](#bucket_copypy) | The rebuilt `storage`, as root, piped over SSH | [`rebuild-storage.md`](rebuild-storage.md) | Copies the backup bucket from another S3 endpoint and proves the copy whole |
| [`rebuild_check.known_hosts`](../../../tools/rebuild_check/known_hosts.py) | The operator's machine | 8 | Removes a host's old SSH host key |
| [`rebuild_check.host`](#rebuild_checkhost) | The operator's machine, over SSH | 12 | Checks one rebuilt host |
| [`rebuild_check.dns`](#rebuild_checkdns) | The operator's machine | 12 | Asks both DNS servers the same questions |
| `restore_all.py --check` | The operator's machine | 1 | Lists the newest backup of each app and its age |

## Dump storage

A VM's dump is its rollback. `backup` is `lvmthin`, which holds VM disks and not
dump files, and the only directory storages (`local`, `tofu-images`) share one
filesystem with less than 100 GB free. Dumps therefore go to a directory storage
on a thin volume of the `backup` volume group, created once on the node. That is
the HDD, away from the NVMe where the rebuilt VMs' disks go.

Take `vgname` and `thinpool` from the `backup` entry of `/etc/pve/storage.cfg`;
on the live node both are `backup`. The pool is overprovisioned, so `lvcreate`
warns that the thin volumes' sizes sum to more than the pool, and autoextend
protection is off: a full pool fails every volume on it. Read the pool's `Data%`
and `Meta%` before creating the volume:

```sh
lvs -o lv_name,lv_size,data_percent,metadata_percent <vgname>
```

A dump is taken and deleted per host, so 100 GB holds the largest (`storage`'s: a
256 GB disk that dumped to a 74 GB archive, since the dump skips zeroed blocks).
Delete one host's dump before taking the next.

```sh
lvcreate -V 100G -T <vgname>/<thinpool> -n vzdump
mkfs.ext4 /dev/<vgname>/vzdump
mkdir -p /mnt/vzdump
echo '/dev/<vgname>/vzdump /mnt/vzdump ext4 defaults,nofail 0 2' >> /etc/fstab
mount /mnt/vzdump
pvesm add dir vzdump --path /mnt/vzdump --content backup --is_mountpoint yes
```

A thin volume returns blocks to the pool only when its filesystem trims them, so a
deleted dump keeps its space in the pool until `fstrim -v /mnt/vzdump` runs.
`retire_vm.sh drop-dump` does both. Remove the storage and the volume when the last
dump is deleted.

## retire_vm.sh

```sh
ssh root@<node> 'bash -s -- dump 204 play' < tools/rebuild_check/scripts/retire_vm.sh
ssh root@<node> 'bash -s -- destroy 204 play' < tools/rebuild_check/scripts/retire_vm.sh
ssh root@<node> 'bash -s -- drop-dump 204' < tools/rebuild_check/scripts/retire_vm.sh
ssh root@<node> 'bash -s -- restore 204 904' < tools/rebuild_check/scripts/retire_vm.sh
```

The VMID is followed by the VM's name in Proxmox, which has to match, so a
mistyped VMID dumps or destroys nothing.

| Action | Refuses when | Leaves behind |
| :--- | :--- | :--- |
| `dump` | The VM is not stopped, the dump storage is not mounted, or the VM already has a dump (so an earlier rebuild's rollback is never replaced by accident). Fails on a dump that is missing, empty or that `zstd -t` cannot read to the end | The dump; prints the free space on the dump volume, so a dump that would not fit is seen before the next one starts |
| `destroy` | The VM is not stopped, the dump storage is not mounted, or there is not exactly one non-empty dump of the VM that passes `zstd -t` again | Nothing of the VM |
| `drop-dump` | | Deletes that VM's dump, log and notes, runs `fstrim -v` on the dump volume and prints the free space |
| `restore` | | `qmrestore` of the dump to a VMID of 900 or above, with new MAC addresses, not started on boot and left stopped |

A restored copy has the old VM's address, so start it only once that address is
free or changed. `RESTORE_STORAGE` names the storage for its disks; unset, they go
back where the dump says they were. `DUMP_STORAGE` and `DUMP_DIR` name the dump
storage and its mount point, `vzdump` and `/mnt/vzdump` by default. The archives
sit in the `dump/` subdirectory of that mount point, where Proxmox keeps the
backups of a directory storage.

## bucket_copy.py

```sh
ssh storage 'sudo python3 - --pin 192.168.20.7' < tools/rebuild_check/scripts/bucket_copy.py
ssh storage 'sudo python3 - --pin 192.168.20.7 --check-only' < tools/rebuild_check/scripts/bucket_copy.py
ssh storage 'sudo python3 - --from r2 --bucket <the r2 bucket>' < tools/rebuild_check/scripts/bucket_copy.py
```

It copies the `homelab-backups` bucket from another S3 endpoint into the SeaweedFS
of the host it runs on, after `cloud_sync` has been deployed there. Nothing is
typed in:

| Part | Where it comes from |
| :--- | :--- |
| Source | A remote of the deployed cloud-sync `rclone.conf`: `seaweedfs`, the reader at the name every client uses, unless `--from` names a cloud target, which restores `storage` from the cloud |
| Destination | The host's own SeaweedFS, with the admin identity read from the running container |
| Image | The one `cloud-sync.service` pins |
| Credentials | A `0600` env file deleted when the run ends; never printed |

It runs `rclone copy --immutable`, so a repeat adds only what arrived since, then
`rclone size` on both sides and `rclone check --size-only`, which exits non-zero
when they differ. `--pin ADDRESS` makes the source's name resolve to `ADDRESS`
inside the copy: once DNS names the new host, the name would otherwise reach the
destination and the check would compare a server with itself. `--check-only`
copies nothing.

## What the checks look at

### restore_all.py --check

Lists the newest backup of each app on every source that could restore it, with
its age, and downloads nothing. It exits non-zero when an app has no source within
30 hours (`--max-age-hours`), which is one nightly run and some slack. A source
that is unreachable or empty is shown as such, since the restore falls back from
SeaweedFS to the app's cloud targets.

The MTIME column compares each source's modification time of that archive with the
instant its name stamps. A difference of more than an hour is shown and named in a
warning, and does not change the exit status: the archive was copied without its
original time, which the relay's `--max-age` and a bucket's lifecycle would read
as young.

### rebuild_check.host

One line per check, over SSH, changing nothing. A host's address is what the lab's
DNS says for its name, so a wrong record fails the check on the host instead of
being trusted.

| Check | Hosts | What it catches |
| :--- | :--- | :--- |
| `address_is_static` | all | The address came from a DHCP lease, not cloud-init |
| `no_dracut_network_file` | all | The initramfs brought the NIC up with DHCP |
| `own_name_resolves_to_its_address` | all | The host's name resolves to loopback on the host |
| `timezone_is_the_inventorys` | all | The host is not on `server_timezone` |
| `no_failed_units` | all | A systemd unit failed |
| `containers_resolve_the_hosts_name` | Docker hosts | A container on `caddy-proxy` resolves the host's name to something else. `docker ps` cannot stand in for it: tinyauth and lldap were both healthy while tinyauth could not reach lldap |
| `containers_are_running_and_healthy` | Docker hosts | A container exited, restarts, is unhealthy or is still starting |
| `ip_forwarding_is_on` | `tailscale` | IPv4 or IPv6 forwarding is not 1 |
| `tailscale_is_online`, `tailscale_carries_its_tag`, `tailscale_routes_are_approved`, `tailscale_key_does_not_expire` | `tailscale` | Read from `tailscale status --self --json`: the node is offline, lacks its tag, advertises routes the policy did not approve, or its key expires |
| `openbao_is_unsealed`, `step_ca_is_healthy`, `tinyauth_reaches_ldap` (no LDAP error lines in tinyauth's last ten minutes), `r2_read_watcher_is_running` | `security` | The service behind each name is down or not installed |

A host of the `network_infra` group has no Docker, so it skips the two container
checks. Add a check for what only another host runs to `HOST_CHECKS` in
[`rebuild_check/host.py`](../../../tools/rebuild_check/host.py).

### rebuild_check.dns

Asks `services` (primary) and `storage` (secondary) directly with `dig`, from the
machine it runs on, and changes nothing. The gateway forwards to both, so a server
that came back with an older zone answers some of the lab's queries while the
other looks fine.

| Check | What it catches |
| :--- | :--- |
| `zones_have_one_serial` | The host zone or the lan zone has a different SOA serial on the two servers, or a server does not answer or holds no such zone. A pass prints each zone's serial, so a run before a rebuild and one after can be compared |
| `resolves_alike: <name>` | The two servers give different addresses for a host's name; for a host Tofu built, both give another address than the generated inventory's |

With no host named it covers every host in `managed_hosts` and `network_infra`, and
`s3.store` in the lan zone, which has no expected address and is checked for
agreement only.
