---
id: PROJ-tofu-migration
title: Tofu Migration
type: project
status: building
blocked: false
summary: Build the isolated 5XX block and run the first restore.yaml against it, then rebuild on the real VMID ranges, cut over, and decommission the old VMs.
super_project: tofu-vm-provisioning
track: migration
depends_on:
  - project: PROJ-tofu-vm-dns
    reason: a rebuilt host has a static address and no DDNS name, so its records must exist before the first rebuild
---

# Tofu Migration

Tofu builds an isolated 5XX block, the first real `restore.yaml` runs against it, and once that is proven the VMs are rebuilt on the real VMID ranges, traffic is cut over and the old VMs are decommissioned. It builds on the Ubuntu and OPNsense modules and the inventory generator described in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md).

## Scope

The 5XX block (OPNsense plus one Ubuntu VM on VLAN 50), the first `restore.yaml` run against it, the rebuild on the real VMID ranges (1XX/2XX/…), the cutover, decommissioning the old VMs, and moving the hand-written `services`, `play`, `security`, `storage` and `tailscale` entries of `inventory.yaml` onto the generated inventory file. `storage` stays up throughout. VMIDs 103–105 and 401–403 aren't in any Ansible inventory and are out of scope. Not in scope: OPNsense day-2 configuration ([`opnsense-config.md`](opnsense-config.md)).

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
| 2 | Cutover to real VMID ranges, decommission old VMs | In progress | the VMs are rebuilt on the real VMID ranges, traffic is cut over, the generated inventory replaces the hand-written entries, and the old VMs are decommissioned with `storage` up throughout |

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
(1XX/2XX/...), cut over, decommission the old VMs. `storage` stays up
throughout every stage — it is the DR restore target.

**Order.** DNS records for Tofu-provisioned VMs
([`tofu-vm-dns.md`](tofu-vm-dns.md)) come first: a rebuilt host has a
static address and no DDNS name, and every generated CNAME points at
`dns_ddns_target`. The first rebuild waits for that project to close.

**One host at a time.** Each rebuild is its own pull request and runs
the same cycle:

1. Back up the host's apps ([`backup.md`](../topics/disaster-recovery/backup.md)).
2. `vzdump` the old VM to the `vzdump` storage ([below](#dump-storage)),
   then destroy it. The dump is the rollback: `qmrestore` it to a 9XX
   VMID.
3. Add the host's module call and `ansible_hosts` entry to the root
   module, apply, and run the inventory generator.
4. Remove the host's `ansible_host` and `ansible_user` from
   `inventory.yaml`, keeping its group membership.
5. Deploy with `deploy.yaml` and restore its apps with `restore.yaml`, as
   [`fire-drill.md`](../topics/disaster-recovery/fire-drill.md) does on the
   scratch host.
6. Delete the dump once the host's apps are confirmed healthy on the new
   VM.

The gateway's rebuild is the last stage of
[`opnsense-config.md`](opnsense-config.md), run with this cutover.

#### Dump storage

`backup` is `lvmthin`, which holds VM disks and not dump files, and the
only directory storages (`local`, `tofu-images`) share one 36 GB
filesystem. Dumps go to a directory storage on a thin volume of the same
volume group, created once on the node. Read `vgname` and `thinpool` from
`/etc/pve/storage.cfg`, and size the volume from the data the hosts hold
(`df -h` on each), since the pool also holds the disks of VMs 202 to 204:

```sh
lvcreate -V <size> -T <vgname>/<thinpool> -n vzdump
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
- [ ] Every VM is rebuilt on the real VMID ranges by Tofu.
- [ ] The generated inventory replaces the hand-written entries, including `tailscale`.
- [ ] The old VMs are decommissioned.
- [ ] `storage` stayed up throughout.
- [ ] The resulting behavior is described in [`docs/topics/infra/vm-provisioning.md`](../topics/infra/vm-provisioning.md) or a new topic doc, not only here.

## Open items

- The order the hosts are rebuilt in, and each host's sizing. Both need
  the live VM configs and the node's free memory.
- How `storage` is rebuilt while it stays up: its VMID is held by the
  live VM, and the cycle above destroys the old VM first. Needs to know
  where SeaweedFS keeps its data.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
