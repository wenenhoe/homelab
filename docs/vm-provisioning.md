# VM Provisioning: Proxmox via OpenTofu

The design record for OpenTofu-driven Proxmox provisioning: VMID/VLAN/IP
scheme, MAC scheme, Ubuntu/OPNsense provisioning, and the boundary with
Ansible. Build status and staged rollout live in
[`docs/projects/tofu-vm-provisioning.md`](projects/tofu-vm-provisioning.md),
not here.

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
| 5XX | Experimental | 50 | `192.168.50.0/24` | Migration staging — see the project doc |
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
`match: macaddress` override below to stay stable across rebuilds.
A Kea static-reservation key was the other option this MAC scheme
would have supported, but that path isn't taken — see the Ubuntu VMs
section for why.

## Ubuntu VMs

Tofu builds the cloud-init template itself (downloads the official
Ubuntu 26.04 cloud image via `local-lvm`) rather than relying on a
pre-existing one, registered as a proper Proxmox template VM in the 1XX
range (e.g. the next free ID below 200) alongside the existing
Windows templates (103–105), then clones from it per VM. Network
config is injected via cloud-init `network-config` at first boot: a
static IP (the VMID-derived address from the scheme above), gateway,
and nameservers, matched to the VM by `match: macaddress` against the
deterministic MAC — no DHCP involved at all. This avoids the
alternative (an Ansible-rendered netplan file post-boot) racing
against whatever address the VM picks up before Ansible can connect
at all, and sidesteps DHCP/Kea entirely rather than working around it
— see
[`netplan-dhcp-identifier.md`](netplan-dhcp-identifier.md) for the
current-fleet bug that's the real motivation for skipping DHCP here.

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

**DNS.** OPNsense's BIND plugin manages zones through its own model —
adding ordinary A-record host overrides via its config API is normal,
supported usage; hand-editing raw zone files or adding custom
`named.conf` directives isn't, and isn't needed here. Kea's DDNS-push
against BIND (RFC 2136 dynamic updates) is a known source of
zone-journal corruption in this class of setup — a documented class of
BIND behavior, not specific to this lab. Since Tofu assigns every
managed VM's IP deterministically at provision time, those VMs don't
need DDNS at all: Phase 2 pushes static host overrides through
OPNsense's API instead, sidestepping the corruption risk entirely for
anything Tofu manages. Non-Tofu-managed DHCP clients (the
`.50`–`.254` pool) have no fixed IP to override statically and keep
using DDNS — the one place this class of risk still applies, since
that pool is for devices Tofu doesn't know about.

Whether Phase 2 stays OPNsense-API-driven, or Tofu-sourced A records
move to a dedicated internal nameserver instead, is an open decision —
see the
[decision draft](decisions/drafts/dedicated-security-bind9-for-tofu-vm-dns.md).

**Boot order.** `order=1` for OPNsense with `up=60` (60s) before any
dependent VM is considered clear to start — gives DHCP/DNS time to come
up before anything else races to request an address or resolve a name.

## Tofu ↔ Ansible handoff

Tofu does not write into `ansible/` directly. Instead, a small generator
script reads Tofu state/outputs (VMID, IP, MAC, hostname per VM) and
produces the inventory data Ansible consumes — keeping each tool's
write-ownership single-purpose, consistent with how `host_vars` /
`app_registry` already split concerns in this repo.

## State backend & secrets

Tofu state lives in a dedicated SeaweedFS S3 bucket (`opentofu-state`)
on `storage` (already S3-compatible; a proper offsite/cloud backend is
a later replacement). This is why `storage` is the one host kept
running through every migration stage — it's a dependency of the
tooling itself, not just of the apps it hosts.

Where Tofu's own secrets (Proxmox API token, OPNsense API key, the
state-backend S3 credential) live is not yet decided — see the
[decision draft](decisions/drafts/tofu-secrets-and-state-backend-location.md)
for the three options under consideration, and the project doc's
Stage 1 for status.
