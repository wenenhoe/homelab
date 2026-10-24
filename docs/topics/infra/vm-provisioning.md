# VM Provisioning: Proxmox via OpenTofu

The design record for OpenTofu-driven Proxmox provisioning: VMID/VLAN/IP
scheme, MAC scheme, Ubuntu/OPNsense provisioning, and the boundary with
Ansible. The move of the existing hosts onto it is tracked in
[`docs/projects/tofu-migration.md`](../../projects/tofu-migration.md),
not here.

OpenTofu owns everything up to "the VM exists, boots, and can be reached
over SSH with the right network config." Ansible's job starts there,
unchanged from today. This doc is the decision record for that boundary
and the scheme both sides depend on — see
[`deployment-flow.md`](../deploy/deployment-flow.md) for what happens once Ansible
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
A VM other than OPNsense never takes an `X01` VMID, because its derived
address would be the gateway's; every other VMID in a range starts at `X02`.

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
(untagged, unless `wan_vlan_id` puts it on a VLAN of the LAN bridge), one on the VLAN-aware LAN bridge that every other VM's NIC
also attaches to, tagged per-VM to whichever VLAN its VMID range implies.

## MAC address scheme

Proxmox's own auto-assigned MACs use OUI `BC:24:11`. Tofu keeps that
prefix (stays recognizable as Proxmox-owned) and encodes the VMID plus
NIC index into the rest: `BC:24:11:{VMID as 4 hex digits}:{NIC index}`
— e.g. VMID 201, NIC 0 → `BC:24:11:00:C9:00`. Deterministic per VMID, so
a rebuilt VM gets the same MAC every time — required for the
MAC-matched network config below to stay stable across rebuilds.
A Kea static-reservation key was the other option this MAC scheme
would have supported, but that path isn't taken — see the Ubuntu VMs
section for why.

## Ubuntu VMs

Tofu builds the cloud-init template itself rather than relying on a
pre-existing one: the `proxmox_ubuntu_template` module downloads the
official Ubuntu cloud image, verifies it against a SHA-256 the caller
supplies, and registers it as a Proxmox template VM in the 1XX range,
next to the existing Windows templates (103–105). The
`proxmox_ubuntu_vm` module then clones it per VM. Network config is
injected through cloud-init at first boot: the module sets the NIC's
deterministic MAC and an `ip_config` holding a static IP (the
VMID-derived address from the scheme above), gateway and nameservers,
and Proxmox renders the cloud-init `network-config` from them,
matching the NIC by its MAC address — no DHCP involved at all. A
hand-written `network-config` would be an uploaded snippet file, which
the provider writes over SSH to the node; `ip_config` needs only the
API token. This avoids the alternative (an Ansible-rendered netplan
file post-boot) racing against whatever address the VM picks up before
Ansible can connect at all, and sidesteps DHCP/Kea entirely rather
than working around it — see
[`netplan-dhcp-identifier.md`](netplan-dhcp-identifier.md) for the
current-fleet bug that's the real motivation for skipping DHCP here.

Default sizing (adjust per host once real usage is observed):

| Host | vCPU | RAM | Disk |
| :--- | :--- | :--- | :--- |
| OPNsense | 2 | 2 GB | 32 GB |
| services / security | 2 | 2 GB | 32 GB |
| play (Minecraft) | 4 | 4 GB | 64 GB |
| storage | 2 | 4 GB | 64 GB+ |

VM disks go on `local-lvm` (NVMe) for performance, except `storage`'s,
which goes on `backup` (HDD): it holds the on-site copy of every backup,
so it must not share a disk with the hosts it protects. The OPNsense ISO and
Ubuntu cloud image go on `tofu-images`, a directory storage that holds
only ISO and import content — both small, one-time downloads, no need
for HDD or NVMe capacity planning around them.

### Ubuntu modules

`tofu/modules/proxmox_ubuntu_template` and
`tofu/modules/proxmox_ubuntu_vm` are called from the root module in
`tofu/`. The template module's `vm_id` defaults to a free ID in the 1XX
range, and `image_url` and `image_checksum` have no default: the root
module passes the dated release directory of the cloud image and the
SHA-256 that release publishes, which are the defaults of
`ubuntu_image_url` and `ubuntu_image_checksum` in `tofu/variables.tf`.
The root module builds the template; it declares no VMs yet.

The template and its clones are `q35` machines booting UEFI (`ovmf`) from a
`4m` EFI disk on the VM datastore with the distribution and Microsoft keys
pre-enrolled, so secure boot is on. The clone
repeats the firmware and the EFI disk, because the provider otherwise plans
SeaBIOS and a `2m` disk over the template's, and a different EFI disk type
replaces the VM. The OPNsense module does not set firmware.

From `vm_id` the VM module derives everything the scheme above fixes: the
VLAN tag, the static `/24` address with `.1` as gateway, and the MAC. It
rejects a VMID outside 2XX to 5XX and one whose last two digits fall
outside 02 to 49, the reserved, gateway and DHCP-pool host parts.
Nameservers default to the VLAN's gateway; `dns_servers` replaces them.
`dns_domain`, the lab's internal zone, has no default: a VM with no search
domain gets a copy of the node's own. Its
defaults are the services/security row of the sizing table, and a larger
host overrides `cores`, `memory_mb` and `disk_gb`. Its outputs are `vm_id`,
`hostname`, `ip_address`, `mac_address` and `inventory_entry`, the one the
inventory generator reads.

```hcl
module "services" {
  source          = "./modules/proxmox_ubuntu_vm"
  node_name       = var.proxmox_node
  vm_id           = 203
  name            = "services"
  template_vm_id  = module.ubuntu_template.vm_id
  admin_username  = "svcadmin"
  dns_domain      = "<internal zone>"
  ssh_public_keys = ["<public half of the Ansible key>"]
}
```

Both modules store their image on `tofu-images`, created once on the node:

```sh
pvesm add dir tofu-images --path /var/lib/tofu-images --content iso,import
```

Deleting a stored file takes `Datastore.Allocate`, which gives full access
to every volume on a storage, so the token holds it on this storage only
(see [Proxmox API token](#proxmox-api-token)). Bumping an image URL
replaces the download, and the old file goes with it. Disks are imported from it
through the API alone; the other route, `file_id` on an `iso` download,
needs SSH to the node. The provider's docs say a `.qcow2` file name is
rejected by Proxmox before 8.4.

`tofu -chdir=tofu test` checks the VMID-derived values and the input
rules against a mocked provider, so it needs no node or credentials. A new
`run` block with its own `module` source needs `tofu init` again before it
is found. The `tofu-checks` CI job runs `tofu fmt -check -recursive`, `tofu validate` and
this test on every change under `tofu/`; run `tofu fmt -recursive` before pushing.

## OPNsense

No cloud-init story exists for OPNsense, so provisioning happens in two
phases:

- **Phase 1, now:** the `proxmox_opnsense_vm` module creates the VM
  shell and attaches the OPNsense installer, and the install/initial
  config is manual. The installer is the `.iso.bz2` of one release, which
  Proxmox downloads, checks against the SHA-256 the caller supplies and
  unpacks. OPNsense publishes no stable "latest" URL, so a newer release
  is a new URL and checksum.
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
[working decision](../../decisions/0040-dns-for-tofu-provisioned-vms/revision-000.md).

The module gives the VM two virtio NICs with MACs from the scheme above,
NIC 0 on the physical WAN bridge and NIC 1 on the VLAN-aware LAN bridge,
both untagged so OPNsense sees every VLAN, and boots the disk before the
installer so an installed VM boots from it. Setting `wan_bridge` to the
LAN bridge and `wan_vlan_id` tags NIC 0 onto a VLAN of it instead, for a
WAN that is an ordinary client of another OPNsense's LAN; NIC 1 stays
untagged. Its `vm_id` is the gateway
VMID of a range, host part 01. The root module declares no OPNsense VM
yet, so the module's call is where its bridges, sizing and image are
passed.

**Boot order.** `order=1` for OPNsense with `up=60` (60s) before any
dependent VM is considered clear to start — gives DHCP/DNS time to come
up before anything else races to request an address or resolve a name.
Tofu does not set it: Proxmox requires `Sys.Modify` on `/` for a startup
order, which is cluster-wide and far wider than the token's role. Set it
once on the VM with `qm set <vmid> --startup order=1,up=60`.

## Tofu ↔ Ansible handoff

Tofu does not write into `ansible/` directly. The root module's
`ansible_hosts` output maps an inventory host name to
`module.<name>.inventory_entry`, which carries the VM's static address and
login user. `tools/tofu_inventory` reads it with `tofu output -json` and
writes `ansible/inventory/tofu-hosts.yaml`, a gitignored file giving each
host its `ansible_host` (the IP, since a static VM has no DHCP lease to
register in DNS) and `ansible_user`. Run it from `tools/` after an apply:

```sh
cd tools && uv run python -m tofu_inventory
```

The generator rejects an entry with extra or missing keys, a name that is
not a lowercase inventory name, or an address that is not IPv4, and a failed
run leaves the previous file in place. `inventory.yaml` keeps only what Tofu
cannot know — group membership — and `ansible.cfg` loads the two files in
that order, so Ansible merges them by host name and the generated address
and user win ([`ansible.md`](../deploy/ansible.md#inventory) covers a run
that passes `-i`). A new VM is a module call, an `ansible_hosts` entry and
a name in its groups. Each tool keeps one job, as `host_vars` and `app_catalog`
already split concerns in this repo.

## Tofu project

The root module is `tofu/` at the repo root. `versions.tf` pins OpenTofu
(`~> 1.13`) and the `bpg/proxmox` provider (exactly), `providers.tf`
configures the provider with an API token, and `.terraform.lock.hcl` is
committed. `main.tf` reads the `pve` node, so `tofu plan` fails on a wrong
endpoint, token or node name instead of passing with nothing to do; that
read is its only call apart from the template build below. The Ubuntu
modules are in `modules/` and their tests in `tests/`; see
[Ubuntu modules](#ubuntu-modules).

OpenTofu is installed on the host that runs it with its official
installer (Debian and Ubuntu). Read the script before running it:

```sh
curl --proto '=https' --tlsv1.2 -fsSL https://get.opentofu.org/install-opentofu.sh -o install-opentofu.sh
chmod +x install-opentofu.sh
./install-opentofu.sh --install-method deb
rm -f install-opentofu.sh
```

`tofu version` must satisfy `required_version` in `versions.tf`. The
provider needs no separate install: `tofu init` fetches it. Run Tofu from
the repo root with `umask 077`, which makes the state file `0600`, and
with `TF_DATA_DIR` set outside the checkout on every command. Without it
`tofu init` unpacks the provider, README included, into `tofu/.terraform/`,
where `check-doc-drift` scans it and fails `pre-commit`:

```sh
umask 077
export TF_DATA_DIR="$HOME/.cache/tofu/homelab"
tofu -chdir=tofu init
tofu -chdir=tofu plan -var-file="$HOME/.config/tofu/credentials.tfvars"
```

To stop repeating the flags, set them in the shell profile. `TF_CLI_ARGS_<command>`
adds arguments to one command only, which `init` needs since it takes no
`-var-file`, and after `cd tofu` no `-chdir` is needed:

```sh
export TF_DATA_DIR="$HOME/.cache/tofu/homelab"
for c in plan apply destroy refresh import console; do
  export "TF_CLI_ARGS_$c=-var-file=$HOME/.config/tofu/credentials.tfvars"
done
```

## State backend & secrets

Tofu state is `tofu/terraform.tfstate` on the host that runs Tofu, ignored
by git. It is the only copy: `git clean -x` deletes ignored files, so it
is never run in the checkout, and a backup is taken after each apply with
`tofu -chdir=tofu state pull` redirected to a `0600` file outside the
checkout. A remote S3-compatible backend (`opentofu-state`) is planned, and
`tofu init -migrate-state` moves existing state into it. The backend
can't be a VM Tofu manages, since Tofu has to be able to rebuild that
VM, which rules out the SeaweedFS on `storage`. A separate small SeaweedFS
instance is the leading idea; where it runs is not decided, and choosing
the host is a decision that needs an ADR before anything is built. The
bucket is created by hand, since SeaweedFS does not create one on first
write ([`backup.md`](../disaster-recovery/backup.md)).

Tofu's own secrets live in a file on the host that runs Tofu, outside the
repo and outside OpenBao, since Tofu must be able to rebuild the host that
runs OpenBao — see the
[decision](../../decisions/0048-where-tofu-credentials-live/revision-000.md).
The file is `~/.config/tofu/credentials.tfvars`, mode `0600` in a `0700`
directory, owned by the operator account, and passed with `-var-file`:

```hcl
proxmox_endpoint  = "https://pve.example.lan:8006/"
proxmox_api_token = "user@realm!tokenid=secret"
```

The endpoint must be `https://`, and TLS verification is on. Setting
`proxmox_insecure = true` in the file skips it, which the provider's own
docs limit to development. The OPNsense API key and, once a remote backend
exists, its S3 credential join this file when their consumers are built.
Git ignores `*.tfvars`, `*.tfvars.json` and state files anywhere in the
tree, and neither the token nor the endpoint appears in the state.

### Proxmox API token

The token is created on the Proxmox node, outside this repo, and this
section is its only record. It belongs to the user `tofu@pve`, which holds
the role `TofuProvision` on the six paths below, and `TofuImageStore` on one. The token ID is
`skeleton` and privilege separation is off, so the token has the user's
rights. The value in the credentials file is `tofu@pve!skeleton=<secret>`.
On the node:

```sh
pveum user add tofu@pve
pveum role add TofuProvision -privs "Sys.Audit,Sys.AccessNetwork,Datastore.Audit,Datastore.AllocateSpace,Datastore.AllocateTemplate,VM.Allocate,VM.Audit,VM.Clone,VM.PowerMgmt,VM.Config.CPU,VM.Config.Memory,VM.Config.Disk,VM.Config.Network,VM.Config.Cloudinit,VM.Config.CDROM,VM.Config.Options,VM.Config.HWType,SDN.Use"
pveum acl modify /nodes/pve --users tofu@pve --roles TofuProvision
pveum role add TofuImageStore -privs "Datastore.Allocate"
pveum acl modify /storage/tofu-images --users tofu@pve --roles TofuProvision,TofuImageStore
pveum acl modify /storage/local-lvm --users tofu@pve --roles TofuProvision
pveum acl modify /storage/backup --users tofu@pve --roles TofuProvision
pveum acl modify /vms --users tofu@pve --roles TofuProvision
pveum acl modify /sdn/zones/localnetwork/vmbr0 --users tofu@pve --roles TofuProvision
pveum acl modify /sdn/zones/localnetwork/vmbr1 --users tofu@pve --roles TofuProvision
pveum user token add tofu@pve skeleton --privsep=0
```

| Path | Used for |
| :--- | :--- |
| `/nodes/pve` | Reading the node, and the image download with its size lookup (`Sys.AccessNetwork`) |
| `/storage/tofu-images` | Storing and removing images, and reading them for the disk import (`Datastore.Allocate`, from `TofuImageStore`, only here) |
| `/storage/local-lvm` | VM disks and cloud-init drives |
| `/storage/backup` | The disk and cloud-init drive of `storage` |
| `/vms` | Creating, cloning, configuring and starting VMs: every VM on the node, Tofu-managed or not |
| `/sdn/zones/localnetwork/vmbr0` | Attaching the OPNsense WAN NIC to the physical bridge |
| `/sdn/zones/localnetwork/vmbr1` | Attaching a NIC to the VLAN-aware bridge |

The role order above matters only on a fresh setup: `TofuImageStore` must
exist before the ACL names it. The image download needs `Sys.AccessNetwork` on the node, or the older
`Sys.Modify` on `/`, which is far wider; the role takes the first.
`TofuProvision` holds every privilege on every path, and Proxmox checks
each one only where it applies. A change that makes Tofu call more of the Proxmox API
widens the role to the privileges it needs and lists them here.
