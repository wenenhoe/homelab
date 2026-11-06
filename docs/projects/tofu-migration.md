---
id: PROJ-tofu-migration
title: Tofu Migration
type: project
status: building
blocked: false
summary: Build the isolated 5XX block and run the first restore.yaml against it, then rebuild the Ubuntu VMs on the real VMID ranges, cut over, decommission the old ones, and move Tofu's state to a remote backend.
super_project: tofu-vm-provisioning
track: migration
---

# Tofu Migration

Tofu builds an isolated 5XX block, the first real `restore.yaml` runs against it, and once that is proven the Ubuntu VMs are rebuilt on the real VMID ranges, traffic is cut over and the old Ubuntu VMs are decommissioned. Tofu's state then moves off the dev VM into a remote backend. The gateway (VM 201) is rebuilt by [`opnsense-config.md`](opnsense-config.md), after this cutover. It builds on the Ubuntu and OPNsense modules and the inventory generator described in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md).

## Scope

The 5XX block (OPNsense plus one Ubuntu VM on VLAN 50), the first `restore.yaml` run against it, the rebuild of the Ubuntu VMs on the real VMID ranges (1XX/2XX/…), the cutover, decommissioning the old Ubuntu VMs, and moving the hand-written `services`, `play`, `security`, `storage` and `tailscale` entries of `inventory.yaml` onto the generated inventory file, and moving Tofu's state from the dev VM to a remote backend. `storage` stays up throughout. VMIDs 103–105 and 401–403 aren't in any Ansible inventory and are out of scope. Not in scope: the production gateway's rebuild (VM 201) and its day-2 configuration, both in [`opnsense-config.md`](opnsense-config.md).

## Decision

No ADR for the first two stages. The design is [`vm-provisioning.md`](../topics/infra/vm-provisioning.md), a topic doc that predates ADRs.

Stage 3 carries out a decision that is not yet made: where the remote state backend runs. It needs its own ADR, and Stage 3 does not start until that revision is `approved` and this doc names it in `decision:`.

## Environment (baseline)

Live `pve` node: 6-core i5-9400, 32GB RAM, NVMe boot SSD (`local` +
`local-lvm`, 1TB) plus a secondary HDD (`backup`, 1TB). This is the
`qm list` the VMID scheme in `vm-provisioning.md` was checked against:

| VMID | Name | Status | Notes |
| :-: | :--- | :--- | :--- |
| 103 | Win10ProKMS | stopped | Template; standalone KMS-activated |
| 104 | Win11Pro | stopped | Template; uses KMS on `services` |
| 105 | Win11ProGPU | stopped | Template |
| 201 | OPNsense | running | Gateway |
| 202 | Tailscale | running | Subnet router, `192.168.20.0/24` |
| 203 | Services | running | Ansible-managed |
| 204 | Play | running | Ansible-managed (Minecraft) |
| 205 | Security | running | Ansible-managed |
| 206 | Storage | running | Ansible-managed; SeaweedFS S3 |
| 401 | Development | running | Runs the repo's tooling (Tofu/Ansible) |
| 402 | ZorinPC | stopped | Desktop |
| 403 | Personal | running | GPU passthrough |

This table is a snapshot, not a tracked value — it drifts as this
project moves real VMs; don't treat it as current once Stage 2 starts.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Build the 5XX block, first `restore.yaml` run | Done | the 5XX block is built by Tofu, isolated from production, and the first `restore.yaml` run against it succeeds |
| 2 | Cutover to real VMID ranges, decommission old VMs | In progress | the Ubuntu VMs are rebuilt on the real VMID ranges, traffic is cut over, the generated inventory replaces the hand-written entries, and the old Ubuntu VMs are decommissioned with `storage` up throughout |
| 3 | Move Tofu's state to a remote backend | Not started | the backend's host is decided by an ADR, `tofu init -migrate-state` has moved the state into it, the dev VM's file is no longer the only copy, and [`vm-provisioning.md`](../topics/infra/vm-provisioning.md#state-backend--secrets) describes the backend |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — the 5XX block and the first restore

The current 2XX hosts are live and can't be edited in place, and
resources on `pve` are tight enough that downsizing during the move is
part of the plan — migration happens in stages rather than a single
cutover.

**The isolated block.** Tofu provisions a new OPNsense + one Ubuntu VM
on the `5XX` block (VLAN 50), fully isolated from production. Its WAN
NIC plugs into the same VLAN-aware trunk bridge as everything else,
tagged into VLAN 20 — an ordinary DHCP client of the *current*
OPNsense's LAN, not the physical WAN bridge. This lets it reach
`storage` (still live, same VLAN) and the internet (NATed through the
current OPNsense) with zero firewall/routing changes on production.

**The first restore.** First real run of `restore.yaml` against the
Stage 1 VM(s): validates disaster recovery and rehearses the actual
cutover mechanics at the same time. See
[`fire-drill.md`](../topics/disaster-recovery/fire-drill.md) for how this doubles as the
restore-path fire drill once OpenTofu is up.

### Stage 2 — cutover

Once the first restore is proven, rebuild on the real VMID ranges
(1XX/2XX/...), cut over, decommission the old Ubuntu VMs. `storage` stays up
throughout every stage — it is the DR restore target.

**Names.** A rebuilt host has a static address and no DDNS name. The
`bind9` role gives it an `A` record from the generated inventory, and every
generated CNAME points at `host_fqdn`
([`bind9.md`](../topics/services/bind9.md#the-host-zone)). The hand-written
record for a host in `host_vars/services.yaml` is deleted in the rebuild's
pull request, since the role refuses a host named both ways.

**Host order.** `play`, `storage`, `security`, `services`, then
`tailscale`. `play` is a leaf and proves the cycle. `storage` comes before
`security` and `services` because every restore reads from it. `services`
comes before `tailscale` because its BIND9 serves the zones every other host
resolves through. `tailscale` is last because the router is the maintainer's
route into the lab. The other four
hosts are reached through the router and do not join the tailnet, so their
rebuilds do not touch it. Each host keeps its current vCPU and memory, and its disk shrinks
to what the host uses plus headroom, on `local-lvm` (NVMe) instead of the
`backup` pool. `storage` is the exception and stays on `backup` (HDD), so
the on-site copy of every backup does not share a disk with the hosts it
protects:

| Host | VMID | vCPU | RAM | Disk | Used today |
| :--- | :-: | :-: | :-: | :-: | :-: |
| `play` | 204 | 4 | 4 GB | 64 GB | 25 GB |
| `tailscale` | 202 | 2 | 2 GB | 16 GB | 6.5 GB |
| `storage` | 206 | 4 | 4 GB | 128 GB (`backup`) | 39 GB |
| `security` | 205 | 4 | 2 GB | 64 GB | 24 GB |
| `services` | 203 | 4 | 2 GB | 64 GB | 39 GB |

**One host at a time.** Each rebuild is its own pull request and runs
the same cycle, which [`rebuild-runbook.md`](../topics/disaster-recovery/rebuild-runbook.md)
lays out with the script that runs each step:

1. Check that every app of the host has a recent backup
   (`restore_all.py --check --host <host>`), back up the host's apps on demand
   ([`backup.md`](../topics/disaster-recovery/backup.md#running-a-backup-now))
   and confirm each archive is in SeaweedFS. For `security`, also take the
   OpenBao snapshot
   ([`openbao-backup-restore.md`](../topics/secrets/openbao-backup-restore.md#running-a-backup)),
   which is not part of that pipeline; the script exits 0 only once R2 and
   B2 both have it. Take a copy of Tofu's state with `tofu state pull`, as
   [State backend & secrets](../topics/infra/vm-provisioning.md#state-backend--secrets)
   describes. It stays on the dev VM until Stage 3 ([risks](#risks)).
2. `vzdump --compress zstd` the stopped old VM to the `vzdump` storage
   ([below](#dump-storage)), then destroy it. The dump is the rollback:
   `qmrestore` it to a 9XX VMID. Then delete the host's Kea reservation and
   lease on the live gateway (`storage` does this at step 9 of
   [Moving `storage`](#moving-storage), since its old VM outlives the new
   one). The new VM holds its address from cloud-init, and a reservation left
   in place would hide a failed static configuration behind a lease.
3. Add the host's module call and `ansible_hosts` entry to the root
   module, apply, and run the inventory generator. The first apply replaces
   the Ubuntu template, which imports the prepared image, so build and stage
   that image first
   ([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#prepared-ubuntu-image)).
   A VM cloned from the stock image keeps a DHCP address instead of its
   static one. On the new host, `ip -4 addr` must show its address without
   `dynamic`, and `/run/systemd/network` must hold no
   `zzzz-dracut-default.network`.
4. Remove the host's `ansible_host` and `ansible_user` from
   `inventory.yaml`, keeping its group membership.
5. Deploy with `deploy.yaml` and restore its apps with
   [`restore_all.py --host <host>`](../topics/disaster-recovery/restore.md#batch-restore-all-apps-disaster-recovery-scenario),
   which leaves the other hosts' apps alone, and add a row for the host's restores to its
   [results](../topics/disaster-recovery/fire-drill.md#results). `security`
   restores OpenBao first, from the step 1 snapshot, as the
   [restore drill](../topics/secrets/openbao-backup-restore.md#restore-drill)
   does: it has no `backup:` entry, so `restore.yaml` does not bring it
   back, and the playbooks read their secrets from it. On the new VM
   `deploy.yaml` cannot run until OpenBao and step-ca are back, so
   [Rebuilding `security`](../topics/secrets/openbao-backup-restore.md#rebuilding-security)
   replaces this step's deploy for that host. Set the host's
   saved fingerprint in the Beszel hub to its new agent's, or the agent is
   refused ([`beszel.md`](../topics/monitoring/beszel.md#rebuilding-a-host)).
6. Delete the dump once the host's apps are confirmed healthy on the new
   VM, then run `fstrim -v /mnt/vzdump` ([below](#dump-storage)).

`storage` can't take the cycle as written: SeaweedFS keeps its data in a
Docker volume on the VM's own root disk, so destroying VM 206 destroys it,
and `storage` has to stay up. It is built beside the old VM at the free
VMID 207 (`192.168.20.7`), and once VM 206 is gone it is built again at VMID 206
(`192.168.20.6`), so the VMIDs and addresses stay contiguous
([below](#moving-storage-to-vmid-206)). Each build has its module call setting `datastore_id` to
`backup`, which needs the `tofu@pve` ACL on that storage
([Proxmox API token](../topics/infra/vm-provisioning.md#proxmox-api-token)),
its buckets are copied across, its record is
flipped to the new address ([below](#moving-storage)), and VM 206 is dumped and destroyed once every
app host's on-demand backup
([`backup.md`](../topics/disaster-recovery/backup.md#running-a-backup-now))
has reached the new VM and a cloud sync started by hand has relayed it.

The gateway (VM 201) isn't rebuilt here. The hosts keep using the live
gateway at `.1` throughout, and [`opnsense-config.md`](opnsense-config.md)'s
last stage rebuilds it from the seed after this cutover, so the hosts and
the network boundary never move together.

#### Moving `storage`

Every client reaches SeaweedFS by name: `s3.store.<lan domain>` is a CNAME to
`storage.<host domain>`, and the `bind9` role builds that `A` record from
`storage`'s `ansible_host`
([`bind9.md`](../topics/services/bind9.md#the-host-zone)). Two things follow.
The flip is the `bind9` run on `services` after the generated inventory
addresses `storage` as `192.168.20.7`. Until then everything that reaches
SeaweedFS by name talks to VM 206, whichever host runs it: the
`seaweedfs_bucket` play checks VM 206's bucket, and the `seaweedfs` remote of
`cloud_sync` reads VM 206.

The copy is S3 to S3, not a copy of the Docker volume. It only reads VM 206,
so `storage` stays up, and archive names are never reused, so
`rclone copy --immutable` can be repeated and a second pass adds only what
arrived since the first.

1. Run the cycle's step 1 for the apps on every host, and take the state
   copy.
2. Add the module call (`vm_id = 207`, `datastore_id = "backup"`, 4 vCPU,
   4 GB, a 128 GB disk) and the `storage` entry of `ansible_hosts`, apply, and
   run the inventory generator. From here `storage` is VM 207 to Ansible, and
   VM 206 is reached by its address. Make the edits listed after these steps
   in the same pull request, since the role refuses a host that a static record
   and the generated one both name.
3. `deploy.yaml --limit storage,localhost`, without `services`, so no
   `bind9` run flips the record yet. VM 207's SeaweedFS starts empty. Its
   cloud-sync timer reads VM 206 by name, so the two timers relay the same
   archives and `--immutable` makes the second a no-op.
4. First pass, on VM 207:
   [`bucket_copy.py`](../../tools/rebuild_check/scripts/bucket_copy.py) does what
   this step describes ([how to run it](../topics/disaster-recovery/rebuild-runbook.md#copying-the-bucket)).
   By hand, run the image that `cloud-sync.service` runs, with
   its hardening flags, on the `caddy-proxy` network. Its remotes are `old`,
   the `cloud-sync-reader` identity at the name every client uses (which still
   resolves to VM 206), and `new`, the admin identity at
   `http://seaweedfs:8333`, VM 207's SeaweedFS reached past Caddy and DNS.
   Both come from `RCLONE_CONFIG_OLD_*` and `RCLONE_CONFIG_NEW_*` variables in
   a `0600` env file that is removed afterwards, with `type` `s3`, `provider`
   `Other` and `force_path_style` `true` as the rendered `rclone.conf` sets:

   ```sh
   docker run --rm --network caddy-proxy --env-file <env file> \
     --cap-drop ALL --security-opt no-new-privileges:true --read-only \
     <the cloud-sync image> copy --immutable old:homelab-backups new:homelab-backups
   ```

   Then `rclone check --size-only old:homelab-backups new:homelab-backups`
   with the same flags reports no difference. Size only, because an object
   written in parts may not keep its ETag.
5. The flip: `deploy.yaml --limit services,localhost --tags infra`. The
   `storage` record now reads `192.168.20.7`, and the primary notifies the new
   secondary.
6. On the live gateway, by hand as for its reservations: add `192.168.20.7` as
   a forward server for the host and `lan_domain` zones, and add it to any
   alias or rule that names `192.168.20.6`. The gateway forwards to the
   secondary, which VM 206 stops being told about.
7. Wait out the zone's TTL (3600 s), then run step 4's copy and check again,
   with `--add-host <the name every client uses>:192.168.20.6` on the
   `docker run`. After the flip that name resolves to VM 207, so without it `old`
   would read the server `new` writes to and every check would pass. List the
   newest object under each `<host>-<app>/` prefix on both sides.
8. `deploy.yaml --limit storage,localhost` again, so the bucket play now
   checks VM 207. Take each app host's on-demand backup, confirm it landed on
   VM 207, and run `sudo systemctl start cloud-sync.service` there: it must
   exit 0.
9. Dump and destroy VM 206 as the cycle's step 2 does. Remove the forward to
   `192.168.20.6` and its reservation from the live gateway.

Until step 9 the flip is undone by removing the `ansible_hosts` entry,
regenerating, restoring the static record and `dns_secondary_address`, and
repeating step 5. An archive that reached VM 207 meanwhile is copied back with
step 4's command reversed.

The edits that move `storage` to `192.168.20.7`:

- `host_vars/services.yaml`: delete the `storage` record. The role generates
  it.
- `inventory.yaml`: keep `storage` in its groups and drop its `ansible_host`
  and `ansible_user`.
- `group_vars/all/main.yaml`: `dns_secondary_address`.
- `sos-inventory.yaml`: the `storage` address.
- `opnsense_gateway`'s defaults: `host_storage` and the second forward server.
  `ansible/tests/test_opnsense_policy.py` fails when any of these four
  differ.

Checks that need the lab and are made before step 4:

- That VM 207 holds `192.168.20.7` from its cloud-init configuration and not
  from a lease. The Kea reservation made for `play` would hide a missing
  prepared image the same way.
- Which aliases, rules and reservations on the live gateway name
  `192.168.20.6`.

One more assumption can only be checked at step 8, since only then does
`cloud_sync` read the copied archives: that the relay finds each one equal to
the cloud's copy. It compares modification times, and rclone keeps the original in object metadata
when it copies. `--immutable` refuses a difference without uploading, so a
failure there changes nothing in the clouds.

#### Moving `storage` to VMID 206

The same copy and flip run again with the numbers swapped: VM 207 is the old
VM, the new one is VMID 206 at `192.168.20.6`, and the edits listed above go back to
`192.168.20.6`. What differs:

- VM 207's module is renamed `storage_old` with a `moved` block and applied on
  its own, since a `moved` block cannot name an address that is still declared.
  The next apply adds `module "storage"` at VMID 206 and publishes it as the
  `storage` entry of `ansible_hosts`; `storage_old` is not published.
- `old` is the name every client uses until the flip, and VM 207 behind it. The
  repeat copy after the flip pins that name to `192.168.20.7` with `--add-host`.
- VM 207 is stopped and dumped with `retire_vm.sh dump 207 storage`, then
  destroyed by removing `storage_old` from the root module and applying, so
  Tofu's state does not keep a VM that is gone. The gateway's forward to
  `192.168.20.7` goes with it.

#### Moving `services`

`services` takes the cycle as written, with three differences from the hosts
before it.

- **It is the DNS primary.** While VM 203 is gone nothing renders a zone, and
  `storage` answers from the copy it holds
  ([`bind9.md`](../topics/services/bind9.md#losing-a-server)). Run
  `cd tools && python3 -m rebuild_check.dns` before the cycle's step 2 and keep
  its output: a pass prints the SOA serial of the host zone and of the lan
  zone, and the two servers must agree before the primary is destroyed. Run it
  again after the deploy. The new primary renders its serials from the clock,
  so each must be higher than the one before and equal on both servers. A
  secondary ignores a transfer from a primary with a lower serial, and the check
  then fails and names both.
- **Its name is generated.** The change that declares the VM deletes the static
  `services` record from `host_vars/services.yaml`, since the `bind9` role
  refuses a host named both ways. The generated record has the same address,
  `192.168.20.3`. The `ns1` record in that zone is written by hand, repeats the
  address and stays.
- **Its apps.** `kms` and `wastebin` have a `backup` and are restored in step 5
  from the rebuilt `storage`, the first restore that reads from it, so
  their row in the fire drill's results is also the first check that an archive
  comes back from that host. Every other app of the host is rebuilt by the
  deploy, including `dashy`, whose data volume
  [is not backed up](../../ansible/inventory/group_vars/all/app_catalog.yaml).

#### Moving `tailscale`

`tailscale` is the subnet router and runs no Docker, so the cycle changes in
four places.

- **No apps.** It has no `backup:` entry, so there is nothing to back up on
  demand or restore, and step 1 is the copy of Tofu's state alone. Step 5 runs
  `network-infra.yaml`, not `deploy.yaml`, and there is no Beszel agent to
  re-pin. `rebuild_check.host` skips the two checks that need Docker and adds
  one for forwarding.
- **At home.** While VM 202 is gone nothing advertises the lab's subnet, so
  run the cycle from the LAN. The Proxmox node joined the tailnet by hand and
  stays reachable over it
  ([Tailnet policy](../topics/infra/network-infra.md#tailnet-policy)).
- **The join.** The rebuilt VM is a new device. The tailnet policy already
  holds the tag and the approval of the route, so the only thing made for the
  run is a single-use key in the console, as
  [`network-infra.md`](../topics/infra/network-infra.md#tailscale-node-configuration)
  describes. Check the device before removing the old one: until then the
  dump's rollback is the old VM with its node key.
- **The policy's `hosts` entry.** It names the router by its tailnet address,
  and a new device gets a new one, so the entry is replaced once the device is
  in, or the policy's tests for the router test an address nothing holds.

#### Dump storage

`backup` is `lvmthin`, which holds VM disks and not dump files, and the
only directory storages (`local`, `tofu-images`) share one filesystem with
less than 100 GB free. Dumps go to a directory storage on a thin volume of
the `backup` volume group, created once on the node. That is the HDD, away
from the NVMe where the rebuilt VMs' disks go. Take `vgname` and `thinpool`
from the `backup` entry of `/etc/pve/storage.cfg`; on the live node both are
`backup`.

The pool is overprovisioned, so `lvcreate` warns that the thin volumes' sizes
sum to more than the pool, and autoextend protection is off: a full pool
fails every volume on it. Read the pool's `Data%` and `Meta%` before creating
the volume:

```sh
lvs -o lv_name,lv_size,data_percent,metadata_percent <vgname>
```

A dump is taken and deleted per host, so 100 GB holds the largest. That is
`storage`'s: a 256 GB disk that dumped to a 74 GB archive, since the dump skips
zeroed blocks. Delete one host's dump before taking the next:

```sh
lvcreate -V 100G -T <vgname>/<thinpool> -n vzdump
mkfs.ext4 /dev/<vgname>/vzdump
mkdir -p /mnt/vzdump
echo '/dev/<vgname>/vzdump /mnt/vzdump ext4 defaults,nofail 0 2' >> /etc/fstab
mount /mnt/vzdump
pvesm add dir vzdump --path /mnt/vzdump --content backup --is_mountpoint yes
```

A thin volume returns blocks to the pool only when its filesystem trims them,
so a deleted dump keeps its space in the pool until `fstrim -v /mnt/vzdump`
runs. Run it after each deletion.

Remove the storage and the volume when the last dump is deleted.

The hand-written `services`, `play`, `security`, `storage` and
`tailscale` entries move over as each host is rebuilt: the generator
([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#tofu--ansible-handoff))
then supplies the host's address and login user, and `inventory.yaml`
keeps only group membership. Until a host is rebuilt its entry stays,
and the generated file is empty.

VM 202 ("Tailscale") is Tofu-unmanaged but not untracked: it is under
interim Ansible management as the `network_infra` group
([`network-infra.md`](../topics/infra/network-infra.md)). It becomes
Tofu-managed at its VMID in this stage, last in the host order, and the
generated inventory then supersedes the hand-written `tailscale` entry
rather than sitting beside it. The rebuild joins the new VM to the tailnet
with the `tailscale_node` role under `tag:subnet-router`, which the tailnet
policy already carries with the approval of the router's route, and a
single-use key made in the console for the run
([`network-infra.md`](../topics/infra/network-infra.md#tailscale-node-configuration)).
The old device is removed in the console afterwards.

The live VM takes `192.168.20.2` from a reservation on the current gateway.
The rebuilt VM carries that address itself, as a static address from
cloud-init under the MAC its module derives, so it needs no reservation. The
production gateway's Kea serves no VLAN 20 zone
([`opnsense-config.md`](opnsense-config.md)), and that gateway is rebuilt after
this cutover, so the old reservation is not carried across and nothing is
waiting for it. The gateway's flows name the router's address, so the rebuilt
VM must keep it.

### Stage 3 — remote state

Tofu's state is a local file on the dev VM, and the five rebuilds each change
it. Once they are done, the state moves into the S3-compatible backend
[`vm-provisioning.md`](../topics/infra/vm-provisioning.md#state-backend--secrets)
plans, so Tofu's record of what it built no longer depends on one VM. The
backend cannot be a VM Tofu manages, and where it runs is the ADR this stage
waits on. The local copies the rebuilds took are deleted once the backend
holds the state and a plan against it shows no change.

## Acceptance criteria

- [x] The 5XX block (OPNsense plus one Ubuntu VM on VLAN 50) is built by Tofu and isolated from production.
- [x] The first `restore.yaml` run against it succeeds, as the restore-path fire drill.
- [ ] Every Ubuntu VM is rebuilt on the real VMID ranges by Tofu.
- [ ] The generated inventory replaces the hand-written entries, including `tailscale`.
- [ ] The old Ubuntu VMs are decommissioned.
- [ ] The rebuilt `tailscale` VM carries its tag, has its route approved without the console and has no key expiry.
- [ ] `storage` stayed up throughout.
- [ ] Every rebuilt host was backed up on demand before its old VM was dumped, and the OpenBao snapshot was taken and restored on the rebuilt `security`.
- [ ] Every rebuilt host's restores are in the fire drill's results.
- [ ] A copy of Tofu's state was taken after each rebuild's apply.
- [ ] Tofu's state is held by a remote backend, and a plan against it shows no change.
- [ ] The resulting behavior is described in [`docs/topics/infra/vm-provisioning.md`](../topics/infra/vm-provisioning.md) or a new topic doc, not only here.

## Risks

Could cause rework or delay but blocks nothing now — no live
vulnerability, incident, or exposure window
([`docs/README.md#public-repo`](../README.md#public-repo)).

- Until Stage 3, every copy of Tofu's state is on the dev VM, so losing that
  VM loses the record of what Tofu built. Retiring the dev VM
  ([`workstation-management.md`](workstation-management.md)) must wait for
  Stage 3.
- The batch restore's `--host`, `--skip` and `--check` against the real manifest, `rebuild_check.host` on any
  real host, `ssh_target` for hosts other than `security`, and the
  [rebuild runbook](../topics/disaster-recovery/rebuild-runbook.md) followed end to end have been exercised by
  tests and a rehearsal only. Each remaining rebuild is their first real run, and a defect it finds is fixed as an
  ordinary change before the next host.

## Open items

- Where the remote state backend runs. It needs an ADR before Stage 3 starts.
  The backend cannot be a VM Tofu manages, so it rules out `storage`, and a
  separate small SeaweedFS instance is the leading idea.
- Whether `tailscale` needs the 2 vCPU and 2 GB the table keeps for it. The
  VM is a routing appliance that runs `tailscaled` and the guest agent and
  no Docker, so it may need less than the hosts the keep-current-size rule
  was written for. At idle the guest used about 200 MB of its 2 GiB and
  `tailscaled` about 50 MB, but an idle reading says nothing about the load
  to come: once the operator host and the laptop replace VM 401, every
  operator session crosses the router
  ([ADR 0097](../decisions/0097-how-a-tailscale-node-is-configured/revision-000.md)).
  Measure its memory, CPU and throughput on the live VM under that traffic,
  over runs that span real operator sessions, and set its row before its
  rebuild; until then the row stands, and the disk shrinks as for every host.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
