---
id: PROJ-tofu-migration
title: Tofu Migration
type: project
status: building
blocked: false
summary: Build the isolated 5XX block and run the first restore.yaml against it, then rebuild the Ubuntu VMs on the real VMID ranges, cut over, and decommission the old ones.
super_project: tofu-vm-provisioning
track: migration
---

# Tofu Migration

Tofu builds an isolated 5XX block, the first real `restore.yaml` runs against it, and once that is proven the Ubuntu VMs are rebuilt on the real VMID ranges, traffic is cut over and the old Ubuntu VMs are decommissioned. The gateway (VM 201) is rebuilt by [`opnsense-config.md`](opnsense-config.md), after this cutover. It builds on the Ubuntu and OPNsense modules and the inventory generator described in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md).

## Scope

The 5XX block (OPNsense plus one Ubuntu VM on VLAN 50), the first `restore.yaml` run against it, the rebuild of the Ubuntu VMs on the real VMID ranges (1XX/2XX/…), the cutover, decommissioning the old Ubuntu VMs, and moving the hand-written `services`, `play`, `security`, `storage` and `tailscale` entries of `inventory.yaml` onto the generated inventory file. `storage` stays up throughout. VMIDs 103–105 and 401–403 aren't in any Ansible inventory and are out of scope. Not in scope: the production gateway's rebuild (VM 201) and its day-2 configuration, both in [`opnsense-config.md`](opnsense-config.md).

## Decision

No ADR. The design is [`vm-provisioning.md`](../topics/infra/vm-provisioning.md), a topic doc that predates ADRs.

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

**Host order.** `play`, `tailscale`, `storage`, `security`, then
`services`. `play` is a leaf and proves the cycle. `storage` comes before
`security` and `services` because every restore reads from it. `services`
is last because its BIND9 serves the zones every other host resolves
through. Each host keeps its current vCPU and memory, and its disk shrinks
to what the host uses plus headroom, on `local-lvm` (NVMe) instead of the
`backup` pool. `storage` is the exception and stays on `backup` (HDD), so
the on-site copy of every backup does not share a disk with the hosts it
protects:

| Host | VMID | vCPU | RAM | Disk | Used today |
| :--- | :-: | :-: | :-: | :-: | :-: |
| `play` | 204 | 4 | 4 GB | 64 GB | 25 GB |
| `tailscale` | 202 | 2 | 2 GB | 16 GB | 6.5 GB |
| `storage` | 207 | 4 | 4 GB | 128 GB (`backup`) | 39 GB |
| `security` | 205 | 4 | 2 GB | 64 GB | 24 GB |
| `services` | 203 | 4 | 2 GB | 64 GB | 39 GB |

**One host at a time.** Each rebuild is its own pull request and runs
the same cycle:

1. Back up the host's apps on demand
   ([`backup.md`](../topics/disaster-recovery/backup.md#running-a-backup-now))
   and confirm each archive is in SeaweedFS. For `security`, also take the
   OpenBao snapshot
   ([`openbao-backup-restore.md`](../topics/secrets/openbao-backup-restore.md#running-a-backup)),
   which is not part of that pipeline; the script exits 0 only once R2 and
   B2 both have it. Take a copy of Tofu's state that is off the dev VM
   ([open items](#open-items)).
2. `vzdump --compress zstd` the stopped old VM to the `vzdump` storage
   ([below](#dump-storage)), then destroy it. The dump is the rollback:
   `qmrestore` it to a 9XX VMID.
3. Add the host's module call and `ansible_hosts` entry to the root
   module, apply, and run the inventory generator.
4. Remove the host's `ansible_host` and `ansible_user` from
   `inventory.yaml`, keeping its group membership.
5. Deploy with `deploy.yaml` and restore its apps with `restore.yaml`, as
   [`fire-drill.md`](../topics/disaster-recovery/fire-drill.md) does on the
   scratch host, and add a row for the host's restores to its
   [results](../topics/disaster-recovery/fire-drill.md#results). `security`
   restores OpenBao first, from the step 1 snapshot, as the
   [restore drill](../topics/secrets/openbao-backup-restore.md#restore-drill)
   does: it has no `backup:` entry, so `restore.yaml` does not bring it
   back, and the playbooks read their secrets from it.
6. Delete the dump once the host's apps are confirmed healthy on the new
   VM.

`storage` can't take the cycle as written: SeaweedFS keeps its data in a
Docker volume on the VM's own root disk, so destroying VM 206 destroys it,
and `storage` has to stay up. It is built beside the old VM at the free
VMID 207 (`192.168.20.7`) with its module call setting `datastore_id` to
`backup`, which needs the `tofu@pve` ACL on that storage
([Proxmox API token](../topics/infra/vm-provisioning.md#proxmox-api-token)),
its buckets are copied across, its record is
flipped to the new address, and VM 206 is dumped and destroyed once every
app host's on-demand backup
([`backup.md`](../topics/disaster-recovery/backup.md#running-a-backup-now))
has reached the new VM and a cloud sync started by hand has relayed it.

The gateway (VM 201) isn't rebuilt here. The hosts keep using the live
gateway at `.1` throughout, and [`opnsense-config.md`](opnsense-config.md)'s
last stage rebuilds it from the seed after this cutover, so the hosts and
the network boundary never move together.

#### Dump storage

`backup` is `lvmthin`, which holds VM disks and not dump files, and the
only directory storages (`local`, `tofu-images`) share one 36 GB
filesystem. Dumps go to a directory storage on a thin volume of the same
volume group, created once on the node. Read `vgname` and `thinpool` from
`/etc/pve/storage.cfg`. A dump is taken and deleted per host, so 100 GB
holds the largest (39 GB used on its root filesystem):

```sh
lvcreate -V 100G -T <vgname>/<thinpool> -n vzdump
mkfs.ext4 /dev/<vgname>/vzdump
mkdir -p /mnt/vzdump
echo '/dev/<vgname>/vzdump /mnt/vzdump ext4 defaults,nofail 0 2' >> /etc/fstab
mount /mnt/vzdump
pvesm add dir vzdump --path /mnt/vzdump --content backup --is_mountpoint yes
```

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
Tofu-managed at its VMID in this stage, and the generated inventory then
supersedes the hand-written `tailscale` entry rather than sitting beside
it.

## Acceptance criteria

- [x] The 5XX block (OPNsense plus one Ubuntu VM on VLAN 50) is built by Tofu and isolated from production.
- [x] The first `restore.yaml` run against it succeeds, as the restore-path fire drill.
- [ ] Every Ubuntu VM is rebuilt on the real VMID ranges by Tofu.
- [ ] The generated inventory replaces the hand-written entries, including `tailscale`.
- [ ] The old Ubuntu VMs are decommissioned.
- [ ] `storage` stayed up throughout.
- [ ] Every rebuilt host was backed up on demand before its old VM was dumped, and the OpenBao snapshot was taken and restored on the rebuilt `security`.
- [ ] Every rebuilt host's restores are in the fire drill's results.
- [ ] Tofu's state has a copy off the dev VM, refreshed after each apply.
- [ ] The resulting behavior is described in [`docs/topics/infra/vm-provisioning.md`](../topics/infra/vm-provisioning.md) or a new topic doc, not only here.

## Open items

- How the buckets are copied from VM 206 to VM 207, and how the flip is
  made once the records exist. Needs the records stage's design and the
  admin identity's reach.
- Where Tofu's state is kept off the dev VM. The state file is the only
  copy of what Tofu built, and each rebuild changes it, but the backup
  [State backend & secrets](../topics/infra/vm-provisioning.md#state-backend--secrets)
  describes lands on that same VM. The remote backend that replaces it is
  its own decision and needs an ADR for its host; the first rebuild needs
  only a place off the VM for the `tofu state pull` copy, settled before
  it.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
