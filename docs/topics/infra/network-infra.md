# Network Infrastructure Hosts

Hosts that support the network itself rather than running Docker/
compose apps — the `network_infra` inventory group. Currently one
host: `tailscale` (VM 202), an existing Tailscale subnet router
brought under Ansible management for
[`monitoring-host-isolation.md`](../../projects/monitoring-host-isolation.md); see
[`off-site-monitoring.md`](../../projects/off-site-monitoring.md) for why (offsite
monitoring's eventual off-site hop reuses this VM's existing route rather
than a new tunnel).

## Why its own group, not `managed_hosts`

`managed_hosts` gets Docker, the `compose`/`compose_app` roles, and
every app-deploy play in `deploy.yaml`. VM 202 runs none of that — it's
a routing appliance, not an app host — so folding it into
`managed_hosts` would mean either deploying Docker to a VM that has no
use for it, or complicating every `deploy.yaml` play with a new
exclusion. `network_infra` stays out of `deploy.yaml` entirely;
`patched_hosts` (an alias of `managed_hosts` + `network_infra`, same
pattern as `app_hosts`) is what `maintenance.yaml` targets instead —
see [`ansible.md`](../deploy/ansible.md#inventory).

## Future: superseded by Tofu

The `tailscale` entry is interim: [`tofu-migration.md`](../../projects/tofu-migration.md)
rebuilds VM 202 as a Tofu-managed VM, and the inventory generator
([`vm-provisioning.md`](vm-provisioning.md#tofu--ansible-handoff)) then
produces this host's entry. Remove the hand-written block from
`inventory.yaml` at that point rather than keeping both.

## `tailscale` (VM 202) — current state

Read directly off the host, not assumed:

| Field | Value |
| :--- | :--- |
| OS | Ubuntu LTS (`resolute`) |
| Tailscale | Installed from the official apt repo (`pkgs.tailscale.com/stable/ubuntu resolute`) by the vendor's install script, which left a one-line `tailscale.list` and a keyring package; `tailscaled.service` active |
| Role | Subnet router — advertises `192.168.20.0/24` (`PrimaryRoutes` in `tailscale status --self --json`) |
| Host zone name | `tailscale.{{ host_domain }}` — same `<host>.{{ host_domain }}` structure as every `managed_hosts` member, a static record in `host_vars/services.yaml`; this is what `inventory.yaml`'s `ansible_host` actually uses |
| LAN address | `192.168.20.2/24` on `ens18`, DHCP-obtained from a reservation on the gateway (`dynamic`, not netplan-static) — descriptive only, `ansible_host` doesn't hardcode this |
| `qemu-guest-agent` | Already installed and active (pre-dates this being under management) |
| SSH admin user | `tsadmin` |
| Client preferences | From `tailscale debug prefs`: `AdvertiseRoutes` is `192.168.20.0/24`, `CorpDNS` is true, the client's own `AutoUpdate` is on (`Check` and `Apply`), `NoSNAT` is false, `RunSSH` and `ShieldsUp` are false, no exit node, and `AdvertiseTags` is empty |
| Forwarding | `net.ipv4.ip_forward` and `net.ipv6.conf.all.forwarding` are 1 and set in `/etc/sysctl.d/99-tailscale.conf` |
| Service files | `tailscaled.service` and `/etc/default/tailscaled` are the package's (`PORT="41641"`, `FLAGS=""`) |
| Key expiry | `tailscale status --self --json` reports none |
| Availability | Not always on while spike VMs share the node and VM 401 is in service; always on once the operator host and the laptop replace VM 401, since every operator session then crosses it ([ADR 0097](../../decisions/0097-how-a-tailscale-node-is-configured/revision-000.md)) |
| Updates | `unattended-upgrades` takes security origins only and its local override only removes unused packages, so Tailscale's repository is outside it. `maintenance.yaml` and the client's own updater (on today) are what upgrade the package |
| Host firewall | None; `ufw` is not installed. `tailscaled`'s own rules accept everything that arrives on `tailscale0`, so the tailnet policy decides what a tailnet source reaches on the node itself |

`192.168.20.2` matches the `.02` host-octet [`vm-provisioning.md`'s VMID
scheme](vm-provisioning.md#vmid--vlan--ip-scheme) would predict for
VMID 202 — but that scheme is written for Tofu-provisioned VMs, VM 202
predates Tofu, and the interface shows a DHCP-obtained lease rather
than a static netplan config. The gateway's DHCP server holds a
reservation for it, as it does for every host, so the address is
effectively permanent. That is not relevant to `ansible_host` now that
it resolves through the host zone the same as every other host, but it is
relevant to whether this host would ever
belong in `sos-inventory.yaml` (static-IP-only, DNS-independent
recovery path). Not added there yet: `reset-network.yaml`'s whole
reason to exist is reaching a host when DNS itself might be down, and
this host is reachable over its own `tailscale0` interface regardless
of this repo's DNS — whether that makes `sos-inventory.yaml` coverage
redundant or still worth having for netplan-reset specifically is an
open question, not a settled "no."

The node carries no tag (`tailscale status --self --json`'s `Self` has
no `Tags` key). What any node is allowed to reach is the tailnet's policy,
described in [Tailnet policy](#tailnet-policy).

Re-authenticating this node after a rebuild ([`tofu-migration.md`](../../projects/tofu-migration.md))
needs an auth key created out of band, and a rebuilt node is a new device.
[ADR 0097 (Tailscale node configuration)](../../decisions/0097-how-a-tailscale-node-is-configured/revision-000.md)
decides that the key is single-use, tagged and supplied at run time, and
that the tag and the route's auto-approval are entries in the policy, which
already holds both ([Tailnet policy](#tailnet-policy)). The role itself is
[`tailscale-node-role.md`](../../projects/tailscale-node-role.md).

## Tailscale node configuration

`playbooks/network-infra.yaml` applies the `tailscale_node` role to the group
([ADR 0097](../../decisions/0097-how-a-tailscale-node-is-configured/revision-000.md)).
The role converges, in order:

1. **Install.** Tailscale's apt repository as a DEB822 source with its key in
   `/etc/apt/keyrings/tailscale.gpg`, installed only if the download is the
   pinned key ([`apt-signing-keys.md`](../deploy/apt-signing-keys.md)), the vendor script's one-line
   `tailscale.list` removed in the same run, the package installed and never
   upgraded, and `tailscaled` enabled and started. Only `maintenance.yaml`
   upgrades the package.
2. **Forwarding.** `/etc/sysctl.d/99-tailscale.conf` sets IPv4 and IPv6
   forwarding when the node advertises routes. A node that advertises none has
   no such file: the role removes one left by an earlier run and turns both
   forwarding values off in the same run.
3. **Join**, only when the node is logged out. It needs `tailscale_node_tag`
   and a key; a logged-out node missing either stops the play before anything
   changes. A logged-in node needs neither.
4. **Preferences**, compared against `tailscale debug prefs` and applied with
   one `tailscale set` for the ones that differ: the advertised routes
   (`tailscale_node_advertise_routes`), the accepted DNS setting
   (`tailscale_node_accept_dns`, on by default) and the client's auto-update,
   which is off on every node. Source NAT is left at the client's default.

The join key is single-use, pre-authorized, tagged and valid for hours, made
in the admin console for the run. It is read from `TAILSCALE_AUTHKEY` on the
operator's machine, passed as one argument of the join command and kept out of
the play's output; it is written to no file.

```sh
cd ansible
ansible-playbook playbooks/network-infra.yaml --limit tailscale,localhost -e network_infra_check=true --diff
read -rs TAILSCALE_AUTHKEY; export TAILSCALE_AUTHKEY   # only to join a logged-out node
ansible-playbook playbooks/network-infra.yaml --limit tailscale,localhost
unset TAILSCALE_AUTHKEY
```

A check run changes nothing, and is asked for with `-e network_infra_check=true`
because `--check` also puts the secrets play in check mode, which fails. It reports the `tailscale set` call a real run
would make, so a preference changed by hand on the node shows up there. On a
node installed by the vendor script, the first run replaces its one-line apt
source and turns the client's auto-update off.

**Adding a route.** Add the CIDR, in the canonical form the node reports it in,
to `tailscale_node_advertise_routes` in `inventory/host_vars/tailscale.yaml`,
after [its grant and auto-approval](#adding-a-grant-for-a-route) are saved in
the tailnet policy. The next run calls `tailscale set`.

## Tailnet policy

The policy is edited by hand in the Tailscale admin console and is coded into OpenTofu later ([ADR 0059 (Tailnet policy)](../../decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md)). It holds explicit grants only: nothing is allowed that no grant names. The saved policy is described here by role, never by device name or address, and its email and tailnet addresses are kept out of the repository.

**Devices.** Every device belongs to the maintainer's one user. No other user's device is on the tailnet.

| Role | Tag | Key expiry |
| :--- | :--- | :--- |
| Subnet router (VM 202) | None until it is rebuilt; then `tag:subnet-router` | None |
| Proxmox node, joined by hand, no approved route | None | Off, since an expired key drops the way to the hypervisor when the router VM is broken |
| Maintainer laptop | None | The domain's default |
| Maintainer phone and tablet, backup clients for when the laptop is out of reach, with the laptop's access | None | The domain's default |

**Policy sections.**

- `hosts` names the laptop, phone, tablet, Proxmox node and router by their tailnet addresses, so a grant and a test read by role. Re-adding a device gives it a new address, which is then updated here.
- `tagOwners` lets the maintainer apply `tag:subnet-router`, and `autoApprovers` approves `192.168.20.0/24` for a node carrying it. No node carries the tag yet; the router's rebuild joins under it.
- `grants` are the flows below. The router and the Proxmox node are sources of nothing.
- `tests` assert every grant and every refusal below. The console refuses a save that fails one.
- There is no `ssh` section and no Funnel attribute, since nothing uses Tailscale SSH or Funnel ([ADR 0097](../../decisions/0097-how-a-tailscale-node-is-configured/revision-000.md) leaves both out).

**DNS.** MagicDNS is on. The global nameserver is a public resolver and needs no grant. Split DNS lists the gateway for `host_domain` and for `lan_domain`. The gateway sits inside the route the router advertises, so a client resolves those names only through the grant on port 53 below. The gateway forwards to both DNS servers of [ADR 0040](../../decisions/0040-dns-for-tofu-provisioned-vms/revision-000.md), and the secondary is not listed beside it: the router's own path to the Internet runs through the gateway, so a second entry would keep no name resolving that the tailnet could still reach.

**Flows.** The laptop, phone and tablet are the only sources.

| To | Port | Why |
| :--- | :--- | :--- |
| VLAN 20 hosts, not the gateway or the router | tcp 22 | SSH to the hosts away from home |
| VLAN 20 hosts, not the gateway or the router | tcp 443 | The apps behind Caddy |
| The gateway's address | tcp and udp 53 | Split-DNS lookups |
| The Proxmox node | tcp 8006 and 22 | Its web interface and a shell when the router VM is broken |

A grant takes a CIDR and no exclusion, so "VLAN 20 hosts, not the gateway or the router" is the subnet split into the CIDRs that cover `.3` to `.255`. No source reaches the router's own address, since the host is managed from the operator host through the gateway and not over the tailnet, and none reaches the gateway's management ports. A remote Minecraft player is not a flow: the only player is a VM behind the same gateway as `play`.

### Changing the policy

The maintainer edits it in the console, and no one else has a way to.

1. Copy the current policy somewhere outside the repository first.
2. Make the edit and read the console's preview before saving. The policy is tailnet-wide, so an edit that tightens access can lock out access in use. "Reset to default" in the console restores the allow-all grant.
3. After the save, check from the laptop a flow the edit should allow and one it should refuse.

### Adding a grant for a route

A new route, for a zone the router will reach, needs three entries in the policy before the router advertises it:

1. A grant whose `src` is the intended device or devices alone and whose `dst` is the route's CIDR, limited to the ports in use.
2. `tests` that accept each port in use at one address of the range and refuse the others, and that refuse every other source. A test cannot take a CIDR, so each address is listed.
3. An `autoApprovers.routes` entry keyed by the CIDR with `tag:subnet-router`, so the router's advertisement is approved without the console.

Save the policy first, then add the CIDR to the router's `tailscale_node_advertise_routes`. The grant is what makes the route reachable, and only to the sources it names.

## Bringing a new `network_infra` host under management

One-time prerequisites, none of which can be automated
by the same Ansible run that depends on them (the same
chicken-and-egg `bootstrap-secrets.yaml`'s own header describes for
secrets):

1. **SSH key** — add the public half of `~/.ssh/proxmox_vm_servers`
   (the key every `managed_hosts` member already trusts) to the
   admin user's `authorized_keys`.
2. **Passwordless sudo** — `ansible.cfg` sets `become_ask_pass = False`
   and nothing in this repo stores a `become` password anywhere, so
   the admin user needs a `NOPASSWD` sudoers entry before any
   `become: true` task (Play 0's Gathering Facts included) can
   succeed.
3. **Python interpreter** — `inventory.yaml`'s
   `ansible_python_interpreter: /usr/bin/python3.14` is a global
   `all.vars` default; confirm it exists on the host (or override it
   per-host) before the first run.
4. **Host zone name** — confirm `host_vars/services.yaml`'s host zone holds a
   record for it (`<host>.{{ host_domain }}`) before assuming a new
   `network_infra` host needs the static-IP fallback pattern instead;
   `tailscale` has one and uses it.

`tailscale` needed the first three — `tsadmin`'s sudo currently
prompts for a password (`sudo -n true` fails with
"interactive authentication is required"), and not the fourth.

## Verifying

```sh
ansible-playbook playbooks/maintenance.yaml --limit patched_hosts,localhost
```

Runs `apt`/`fwupd` against every `patched_hosts` member,
`qemu_guest_agent` against `network_infra` only, and then the
`host_hardening` baseline against every `patched_hosts` member. No
`deploy.yaml` equivalent exists for this group — see "Why its own group"
above.
