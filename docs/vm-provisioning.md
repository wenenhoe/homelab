# VM Provisioning: Proxmox via OpenTofu

OpenTofu owns everything up to "the VM exists, boots, and can be reached
over SSH with the right network config." Ansible's job starts there,
unchanged from today. This doc is the decision record for that boundary
and the scheme both sides depend on — see
[`deployment-flow.md`](deployment-flow.md) for what happens once Ansible
takes over.

## VMID / VLAN / IP scheme

VMID-hundred ranges follow the existing numbering convention (from
notes, not introduced by this doc); each networked range maps to its own
VLAN/subnet:

| VMID range | Purpose | VLAN | Subnet | This repo's scope |
| :--- | :--- | :--- | :--- | :--- |
| 1XX | Templates | — (not networked) | — | Tofu's own cloud-init Ubuntu template lands here |
| 2XX | Production — Services | 20 | `192.168.20.0/24` | Primary target — current managed hosts + OPNsense |
| 3XX | Production — Others | 30 | `192.168.30.0/24` | Reserved, unused today |
| 4XX | Production — Desktops | 40 | `192.168.40.0/24` | **Out of scope** — GPU passthrough/manual OS installs, not cloud-init-able the same way |
| 5XX | Experimental | 50 | `192.168.50.0/24` | Migration staging (see below) |
| 6XX–8XX | Unassigned | — | — | Reserved for future ranges as needed |
| 9XX | Archived | — (not running) | — | No networking required |

`X00` and `1000+` are reserved and never assigned to a real VM — so
within a range, `vlan_id = (vmid // 100) * 10`, `host_octet = vmid % 100`
never produces a `.0` host address to collide with. `.1` in every
networked VLAN is reserved for OPNsense's own sub-interface (the
gateway), independent of whether a VM literally holds the `X01` VMID.

Within each VLAN's `/24`, addresses are split so Tofu-managed static IPs
and Kea's dynamic pool never collide:

- `.1`–`.49` — gateway + Tofu-provisioned VMs (static, VMID-derived)
- `.50`–`.254` — Kea DHCP pool for anything not Tofu-managed (laptops, phones, non-provisioned devices)

VM 401 ("Development") is the workstation used to develop this repo and
likely to run `tofu apply`/`ansible-playbook` itself — worth calling out
explicitly if so, since that makes it a dependency of the tooling, not
just another 4XX desktop, even though it stays outside Tofu/Ansible's
management scope either way.

Both OPNsense NICs are `virtio`: one on the physical WAN bridge
(untagged), one on the VLAN-aware LAN bridge that every other VM's NIC
also attaches to, tagged per-VM to whichever VLAN its VMID range implies.

## MAC address scheme

Proxmox's own auto-assigned MACs use OUI `BC:24:11`. Tofu keeps that
prefix (stays recognizable as Proxmox-owned) and encodes the VMID plus
NIC index into the rest: `BC:24:11:{VMID as 4 hex digits}:{NIC index}`
— e.g. VMID 201, NIC 0 → `BC:24:11:00:C9:00`. Deterministic per VMID, so
a rebuilt VM gets the same MAC every time — required for the netplan
`match: macaddress` override to stay stable across rebuilds, and usable
later as a Kea static-reservation key if any VLAN needs one.

## Ubuntu VMs

Tofu builds the cloud-init template itself (downloads the official
Ubuntu 26.04 cloud image via `local-lvm`) rather than relying on a
pre-existing one, registered as a proper Proxmox template VM in the 1XX
range (e.g. the next free ID below 200) alongside the existing
Windows templates (103–105), then clones from it per VM. Network config — including the `dhcp-identifier: mac`
override needed for OPNsense compatibility — is injected via cloud-init
`network-config` at first boot, keyed off the deterministic MAC above.
This avoids the alternative (an Ansible-rendered netplan file post-boot)
racing against whatever address the VM picks up before Ansible can
connect at all.

Default sizing (adjust per host once real usage is observed):

| Host | vCPU | RAM | Disk |
| :--- | :--- | :--- | :--- |
| OPNsense | 2 | 2 GB | 32 GB |
| services / security | 2 | 2 GB | 32 GB |
| play (Minecraft) | 4 | 4 GB | 64 GB |
| storage | 2 | 4 GB | 64 GB+ |

VM disks go on `local-lvm` (NVMe) for performance; the OPNsense ISO and
Ubuntu cloud image go on `local` (dir storage, ISO/template content
type) — both small, one-time downloads, no need for HDD or NVMe capacity
planning around them.

## OPNsense

No cloud-init story exists for OPNsense, so provisioning happens in two
phases:

- **Phase 1, now:** Tofu creates the VM shell, attaches the latest
  OPNsense ISO (fetched fresh from OPNsense's official mirror on every
  build, not cached locally), and the install/initial config is manual.
- **Phase 2, later:** day-2 config (Kea, VLAN interfaces, firewall
  rules) automated via OPNsense's config API once the VMID→IP mapping is
  fully code-driven.

**DNS.** OPNsense's bind9 must be managed through OPNsense itself (no
direct file access — same constraint as its UI/API-only config model).
The existing Kea-DDNS-push design is what causes the journal corruption;
since Tofu now assigns every managed VM's IP deterministically at
provision time, DDNS is dropped in favor of static host overrides,
pushed through OPNsense's API in phase (c). Non-Tofu-managed DHCP
clients (the `.50`–`.254` pool) have no fixed IP to override statically
and keep using DDNS.

**Boot order.** `order=1` for OPNsense with `up=60` (60s) before any
dependent VM is considered clear to start — gives DHCP/DNS time to come
up before anything else races to request an address or resolve a name.

## Migration staging

The current 2XX hosts are live and can't be edited in place, and
resources on `pve` are tight enough that downsizing during the move is
part of the plan. Migration happens in stages rather than a single
cutover:

1. **Stage 1** — Tofu provisions a new OPNsense + one Ubuntu VM on the
   `5XX` block (VLAN 50), fully isolated from production. Its WAN NIC
   plugs into the same VLAN-aware trunk bridge as everything else,
   tagged into VLAN 20 — an ordinary DHCP client of the *current*
   OPNsense's LAN, not the physical WAN bridge. This lets it reach
   `storage` (still live, same VLAN) and the internet (NATed through the
   current OPNsense) with zero firewall/routing changes on production.
2. **Stage 1.5** — first real run of `restore.yaml` against the Stage 1
   VM(s): validates disaster recovery and rehearses the actual cutover
   mechanics at the same time.
3. **Stage 2** — once restore is proven, rebuild on the real VMID ranges
   (1XX/2XX/...), cut over, decommission the old VMs. `storage` stays up
   throughout every stage — it holds both the Tofu state backend and the
   DR restore target.

## Tofu ↔ Ansible handoff

Tofu does not write into `ansible/` directly. Instead, a small generator
script reads Tofu state/outputs (VMID, IP, MAC, hostname per VM) and
produces the inventory data Ansible consumes — keeping each tool's
write-ownership single-purpose, consistent with how `host_vars` /
`app_registry` already split concerns in this repo.

## State backend & secrets

Tofu state lives in the SeaweedFS S3 bucket on `storage` (already
S3-compatible; a proper offsite/cloud backend is a later replacement).
This is why `storage` is the one host kept running through every
migration stage — it's a dependency of the tooling itself, not just of
the apps it hosts.

Proxmox API token and OPNsense API key are Tofu-only secrets, kept
separate from `secrets_registry.yaml`/`bootstrap_secrets.py` since
Ansible never reads them — likely a small gitignored `.tfvars` plus its
own bootstrap helper, mirroring that pattern without merging into it.
