# OPNsense VM

How Tofu builds the OPNsense gateway's VM: the `proxmox_opnsense_vm` module, the
seed disk that holds its first configuration, and the script that answers the
importer at the first boot. What the gateway is then configured with is the
[gateway play](opnsense-gateway.md). The first configuration comes from a seed disk
the importer reads at the first boot
([ADR 0089 (OPNsense configuration)](../../../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md)).

The root module declares the production gateway in `tofu/opnsense.tf`
([below](#the-production-gateway)), and the module's other callers are the
[scratch gateway](opnsense-scratch-gateway.md) and the tests.

```mermaid
flowchart LR
    img["OPNsense nano image<br/>(.img.bz2, one release)"] -- "fetch_image.sh or<br/>stage_image.sh" --> raw[("tofu-images<br/>import/ .raw")]
    cred[("credentials file")] --> seed["build_seed.sh<br/>seed.img"]
    raw --> mod["proxmox_opnsense_vm<br/>(started = false)"]
    seed --> mod
    mod --> fb["first_boot.sh<br/>starts VM, answers importer"]
    fb --> out["console.log, result.json,<br/>gateway-cert.pem"]
    out --> play["opnsense.yaml play"]
```

## The module

| Aspect | Behaviour |
| :--- | :--- |
| `vm_id` | The gateway VMID of a block of 50, host part 01 or 51 (201 by default) |
| NICs | Two `virtio` NICs with MACs from the [MAC scheme](../vm-provisioning.md#mac-address-scheme). NIC 0 on the physical WAN bridge, NIC 1 on the VLAN-aware LAN bridge, both untagged so OPNsense sees every VLAN |
| Startup | The VM starts at the node's boot. `startup_order` puts it at that place in the node's order, with `startup_up_delay` seconds (30 by default) before the next VM starts, so the gateway is up before the VMs behind it |
| WAN as a client | Setting `wan_bridge` to the LAN bridge and `wan_vlan_id` tags NIC 0 onto a VLAN of it instead, for a WAN that is an ordinary client of another OPNsense's LAN. NIC 1 stays untagged |
| System disk | The only boot device, imported at `disk_gb`. The image is 3 GB and the gateway grows its root file system into the rest at the first boot |
| Console | A serial port on a socket |
| Seed | When `seed_image_path` names a raw disk image holding `conf/config.xml`, the module uploads it as import content under the VM's lowercased name and attaches it as `scsi1`. It is needed for the first boot only: [`first_boot.sh`](#first-boot) detaches the disk afterwards, and unsetting `seed_image_path` makes Tofu drop the import file |
| `started` | The caller sets `started = false` when a script on the node answers the importer, because that script must be connected to the serial socket before the first boot passes the importer's prompt. `started` applies only when the VM is created: a later apply neither starts nor stops it, so a change of it never powers a running gateway off |
| Boot order | Tofu does not set it. Proxmox requires `Sys.Modify` on `/` for a startup order, which is cluster-wide and far wider than the token's role. Set it once on the VM with `qm set <vmid> --startup order=1,up=60`, so the gateway starts first and has 60 s before any dependent VM, giving DHCP and DNS time to come up |
| Names | The gateway runs no authoritative DNS and registers no name. A Tofu-built VM's name is an `A` record BIND9 on `services` renders from the generated inventory, and the gateway forwards the zone to `services` and `storage` ([`bind9.md`](../../services/bind9.md#the-host-zone)). A client in the `.50`–`.254` DHCP pool has no name |

## Image

OPNsense publishes the image only as the `.img.bz2` of one release, and Proxmox
refuses to decompress a download of import content. There is no stable "latest"
URL, so a newer release is a new URL and checksum.

| Way | How | Use when |
| :--- | :--- | :--- |
| Module downloads | `image_url` and `image_checksum`: the host running Tofu downloads with `fetch_image.sh`, checks the SHA-256, unpacks into `image_cache_dir` (about 3.5 GB; `.image-cache/` is git-ignored) and uploads the unpacked image as import content. A mismatch removes the download and fails the apply before anything is uploaded. Needs `curl`, `bunzip2` and `sha256sum` or `shasum` | Default |
| Image already on the node | `image_volume_id` (`<datastore>:import/<name>.raw`): nothing is downloaded or uploaded and the system disk is imported from that volume | The node holds the unpacked image. The [scratch gateway](opnsense-scratch-gateway.md#image-staging) stages it there |

Exactly one of the two ways must be given, and the plan fails otherwise.

Connections from a workstation to the Proxmox API dropped now and then during the spike runs (an
upload closed mid-transfer, a VM create answered with an empty reply), and three tries in a row of
the 3 GB image upload failed. The scratch gateway's script has the node download and unpack the
image once, so a run uploads none. The cause of the drops is not found, the seed and the other
uploads still go through the API, and the module has no retry of its own.

## Seed disk

`seed/build_seed.sh OUTPUT_DIR --lan-ip ADDRESS --operator-host ADDRESS` writes `OUTPUT_DIR/seed.img`, the
file the module's `seed_image_path` takes. It needs `python3`, `openssl`, `sfdisk`,
mtools and `xmllint`. It starts from OPNsense's own sample `config.xml`
(`seed/SAMPLE_SOURCE.txt` names its release) and sets:

| Setting | Value |
| :--- | :--- |
| NICs | `vtnet0` is the WAN, `vtnet1` the LAN |
| LAN address | `--lan-ip` |
| VLANs | A device `vlan0.<tag>` on the LAN device for each tag of `--vlans` (20, 25, 30, 35, 40, 45, 50 and 55 unless overridden), with an interface at `192.168.<tag>.1/24` |
| Hostname and domain | Domain `OPNsense.internal` unless overridden: the name the play verifies the GUI certificate for |
| Time zone | `--timezone`, `Asia/Singapore` by default, the inventory's `server_timezone` |
| Management reach | Anti-lockout off, so the gateway admits no host to the GUI, API and SSH ports unless a rule does. The GUI and API listen on the LAN and the VLAN interfaces, never the WAN |
| LAN rules | The sample's two allow-all rules are removed. One pass rule per `--operator-host` (an address in the LAN network, one or more, required) admits that host to the gateway's port 443 on the LAN, and nothing else is admitted there |
| Console | The serial port |
| IPv6 | Off: no system-wide allowance and no IPv6 address method on the WAN or LAN |
| Root password | Set from the credentials file |
| GUI login | A one-time password in front of it: a `TOTP` authentication server which the GUI uses, and a seed on root |
| API user | One, holding only the privileges that cover the play's calls, the scratch update and the diagnostics (system information, firmware, aliases, filter rules, Kea DHCPv4, dnsmasq and Unbound), not `page-all` |

The operator-host rule is how the play's first apply reaches the gateway, before the play has written its guard rule, which names only the zone interfaces. It is a legacy rule, so the API neither lists nor removes it: remove it in the GUI's LAN rules once no host needs the untagged LAN to reach the gateway, at the latest when VM 401 is retired.

OPNsense has no option left to keep console logins off the one-time-password rule,
so the console menu is not password-protected: whoever can open the VM's console in
Proxmox reaches it, and it is the way in when the token is lost. The API user
authenticates by key.

**Credentials.** The root password, API key, API secret and root's OTP seed (base32,
for an authenticator app) are the variables `opnsense_root_password`,
`opnsense_api_key`, `opnsense_api_secret` and `opnsense_root_otp_seed` in the
[credentials file](state-and-credentials.md#credentials-file).

- The builder reads them and appends generated ones when the file holds none of the
  first three, so a rebuilt gateway keeps the credentials the play holds. A file that
  holds the first three without a seed gets one appended.
- The seed carries only a hash of the password and of the secret, and the OTP seed
  itself, which the gateway needs in the clear.
- A credentials file that others can read, or that holds only some of the first
  three, stops the build.
- Tofu warns that these variables are undeclared when it reads the file, which does
  no harm.

## First boot

The importer is offered only at the first boot, so the module is applied with
`started = false` and `first_boot/first_boot.sh VMID OUTPUT_DIR` starts the VM and
answers the importer. It runs on the operator host with `NODE` set to the Proxmox
node's ssh target; the node needs `python3`.

1. It refuses a VM that is not stopped, copies `import_seed.py` to the node and runs
   `qm start`.
2. It runs the driver beside the VM's serial socket with the seed's root password on
   stdin, read from the credentials file, so the password reaches neither a command
   line nor the node's disk.
3. The driver names the seed disk (`da1`) to the importer, logs in at the console
   with the seed's root password when the console asks for one (a login prompt that
   the menu follows within five seconds is not answered) and reads the web GUI's
   certificate off the console.
4. `OUTPUT_DIR` holds `console.log`, `result.json` and `gateway-cert.pem`, the CA
   file the play pins. The driver refuses a certificate that does not match the
   fingerprint the console banner prints, and the script removes the output if it
   finds the password in it.
5. Once the importer has taken the seed, the script unplugs the seed disk (`scsi1`,
   or `SEED_SLOT`) from the running VM, deletes the volume it leaves behind and reads
   the VM's running configuration and the datastore back. The disk holds root's
   one-time-password seed in the clear and the gateway never reads it again, so it
   must not stay in the VM or in a dump of it. A disk that is still there fails the
   script with the volume named, after the certificate has been brought back.

The import file is still on the node after the script. Unset `seed_image_path` and
apply: Tofu drops the file, and the VM, which no longer has the disk, shows no
change. Applying again with `seed_image_path` still set would attach a seed again.

A node that takes a password is reached through a master connection opened by hand
(`ssh -fN -M -S /tmp/opn-ssh.sock root@pve`) and named in `SSH_CONTROL_PATH`. A first
boot that did not take the seed cannot be repeated on the same VM: destroy it and
apply the module again.

## The production gateway

`tofu/opnsense.tf` calls the module for VMID 201: the name `OPNsense`, two cores, 2 GiB, `vmbr0`
for the WAN, `vmbr1` for the LAN and startup order 1. Its NICs carry the MACs the MAC scheme
derives from VMID 201 (`BC:24:11:00:C9:00` and `BC:24:11:00:C9:01`). It sets `started = false`,
so a create leaves the VM stopped and [`first_boot.sh`](#first-boot) starts it; a later apply
never starts or stops it. The image is the pinned release's unpacked
copy in the images datastore (`opnsense_image_volume_id`), the one the scratch gateway's
runs stage. The seed is `opnsense_seed_image_path`, null in the steady state.

While a VM holds VMID 201, an apply that creates one fails, so a rebuild destroys the old VM
first ([below](#rebuilding-the-production-gateway)). The checks before a create:

- `tofu plan` shows the gateway VM and the seed file as the only additions.
- `pvesm list tofu-images --content import` on the node lists the image under the name the
  variable gives. When it does not, stage it as `scratch_gateway.sh` does, with
  `tofu/scratch/opnsense/stage_image.sh`.
- The seed was built with the LAN address of the gateway and the operator host's address
  ([above](#seed-disk)).

The create is `tofu apply -var-file="$HOME/.config/tofu/credentials.tfvars"
-var opnsense_seed_image_path="$HOME/opnsense-seed/seed.img"`, after which `first_boot.sh`
takes the seed. When it is done, apply again without the seed variable. The startup order
needs `Sys.Modify` on `/`, which the Tofu user does not hold, so the create fails with a
403 until it is granted for the create
([the credentials topic](state-and-credentials.md#proxmox-api-token) says how, and to revoke it).

The image is OPNsense 26.1.6 and the play is pinned to 26.1.11, so the gateway is updated
between the first boot and the first apply of the play. The update script of the scratch
gateway runs from the operator host, which reaches the gateway's port 443 on the LAN and
needs no more than the seed admits:

```sh
printf 'API_KEY=%q\nAPI_SECRET=%q\nLAN_IP=ADDRESS\n' KEY SECRET > ~/.opnsense-update.env   # mode 0600, removed after
bash tofu/scratch/opnsense/update_gateway.sh ~/.opnsense-update.env CERT 26.1.11 OUTPUT_DIR
```

`KEY` and `SECRET` are the credentials file's `opnsense_api_key` and `opnsense_api_secret`,
and `CERT` is the `gateway-cert.pem` the first boot wrote. The gateway reboots, and the
script fails unless it answers on 26.1.11 afterwards with the seeded key still accepted.
Before the play has written its rules the operator host reaches only port 443, so the
snapshot a run of the play is preceded by is taken on the node, with `qm snapshot`, and not
with the snapshot token over the API.

### Rebuilding the production gateway

A rebuild replaces the VM with one built from the seed, so the whole lab is offline while the
gateway is down. What it needs:

- **Rehearsal.** A scratch gateway built from the same seed and the same play, with the same
  `-e` variables, passes `tofu/scratch/opnsense/acceptance/acceptance.sh` (`--check` clean, the
  stale-forward and stray-rule round trips, the GUI login and the API key's scope) and the flow
  list's probes before the production gateway is touched.
- **The operator host.** It runs behind the gateway, so it loses the node, the host zone's DNS and
  the Internet when the gateway stops. Before the window it takes a fixed address on the
  untagged LAN for its return (the address `build_seed.sh` takes as `--operator-host`) and its NIC
  moves to `vmbr0`, where it reaches the node without the gateway. Its hosts file maps the node's
  name to the node, because the Proxmox endpoint is addressed by name and the gateway's DNS is
  down. Whether the host should keep a path of its own is an open question.
- **The router.** The rebuilt gateway carries the MACs the module derives from VMID 201, not the
  old VM's, so the physical router sees a new WAN client. Check before the window whether it
  holds a DHCP reservation or a port forward for the old WAN MAC and move it to the new one.
- **The disk and machine type.** The rebuilt gateway is `q35`, with a disk at least as large as
  what the old gateway uses.
- **The variables** the play needs ([above](opnsense-gateway.md#variables-the-play-needs)) and the
  [credentials file](state-and-credentials.md#credentials-file).

The order:

1. Move the operator host to `vmbr0` as above and build the seed
   (`seed/build_seed.sh ... --lan-ip ADDRESS --operator-host ADDRESS`).
2. Stop the gateway, then dump it and destroy it with
   [`retire_vm.sh`](../../disaster-recovery/rebuild-tools.md) (`dump`, then `destroy`, each with the
   VM's name).
3. Apply the root module with `opnsense_seed_image_path` to create VM 201, with the startup order's
   temporary grant ([above](#the-production-gateway)).
4. Run `first_boot.sh`, then apply again without the seed variable.
5. Move the operator host's NIC to `vmbr1`, untagged, with its fixed address, and map
   `OPNsense.internal` to the gateway's LAN address in its hosts file.
6. Update the gateway to the pinned release, snapshot it on the node, run the play with
   `--check --diff`, then apply it with `opnsense_gateway_operator_not_listed_ok` set (the gateway
   sees the operator host at its untagged address and the alias lists its VLAN address), and check
   the play is clean again.
7. Set the operator host's NIC tag to its VLAN and give it its static address in the file netplan
   reads for it (the gateway's DHCP answer for the reservation carries no default route). Check
   the gateway answers on 443 from it and that `--check` is clean from that address without the
   override. The Proxmox console is the way in when it does not.
8. Run the flow list's probes, delete the snapshots and revoke the grant. Delete the dump
   (`drop-dump`) only when the hosts behind the gateway are confirmed healthy.

**Rollback.** The dump is the way back: destroy the rebuilt VM and restore the dump to VMID 201 by
hand with `qmrestore`, which brings the old VM's MACs back with it.
`retire_vm.sh restore` is not that: it refuses a VMID below 900 and gives the copy new MACs.
Inside the rebuild, a snapshot of the gateway before the update and another after it are the way
back.

The seed's legacy rule for the operator host's untagged address admits a host nobody uses once the
operator host has moved to its VLAN. Remove it in the GUI's LAN rules at the latest when VM 401 is
retired ([`vm-401-retirement.md`](../../../projects/vm-401-retirement.md)). When VM 252 takes over,
its address in VLAN 25 replaces VM 401's in `opnsense_gateway_operator_hosts` and the guard rule
admits it through the management zone's interface.
