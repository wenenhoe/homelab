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

## Built by Tofu

`tailscale` is a Tofu-provisioned VM at VMID 202, declared in the root module like
the app hosts. The inventory generator
([`vm-provisioning.md`](vm-provisioning.md#tofu--ansible-handoff)) supplies its
address and login user, so `inventory.yaml` keeps only its group membership, and
its host zone record is generated from that address
([`bind9.md`](../services/bind9.md#the-host-zone)).

## `tailscale` (VM 202) — current state

What the Tofu module and the role leave on the host. `rebuild_check.host tailscale`
checks the address, forwarding, tag, approved route and key expiry:

| Field | Value |
| :--- | :--- |
| OS | Ubuntu LTS (`resolute`) |
| Tailscale | Installed by the `tailscale_node` role from Tailscale's apt repository ([Tailscale node configuration](#tailscale-node-configuration)); `tailscaled.service` active |
| Role | Subnet router — advertises `192.168.20.0/24`, and `PrimaryRoutes` in `tailscale status --self --json` holds it once the policy has approved it |
| Tag | `tag:subnet-router` (`Tags` of `Self` in `tailscale status --self --json`) |
| Host zone name | `tailscale.{{ host_domain }}`, a record the `bind9` role generates from the host's address; `inventory.yaml`'s group entry holds no address |
| LAN address | `192.168.20.2/24`, static from cloud-init, the address VMID 202 derives ([`vm-provisioning.md`](vm-provisioning.md#vmid--vlan--ip-scheme)); it needs no reservation on the gateway |
| `qemu-guest-agent` | Applied to the group by `maintenance.yaml` |
| SSH admin user | `tsadmin` |
| Client preferences | Set by the role: the advertised routes, the accepted DNS setting and the client's auto-update off |
| Forwarding | `net.ipv4.ip_forward` and `net.ipv6.conf.all.forwarding` are 1 and set in `/etc/sysctl.d/99-tailscale.conf` |
| Service files | `tailscaled.service` and `/etc/default/tailscaled` are the package's (`PORT="41641"`, `FLAGS=""`) |
| Key expiry | None: `KeyExpiry` of `Self` in `tailscale status --self --json` is null |
| Availability | Not always on while spike VMs share the node and VM 401 is in service; always on once the operator host and the laptop replace VM 401, since every operator session then crosses it ([ADR 0097](../../decisions/0097-how-a-tailscale-node-is-configured/revision-000.md)) |
| Updates | `unattended-upgrades` takes security origins only and its local override only removes unused packages, so Tailscale's repository is outside it. `maintenance.yaml` is what upgrades the package, since the role turns the client's own updater off |
| Host firewall | `tailscaled`'s own rules accept everything that arrives on `tailscale0`, so the tailnet policy decides what a tailnet source reaches on the node itself |

The gateway's flows name `192.168.20.2`, so a rebuilt VM keeps it. The host is in
`sos-inventory.yaml` with that address, the DNS-independent list
`reset-network.yaml` uses when DNS itself might be down.

The node carries `tag:subnet-router`. The policy's `tagOwners` and `autoApprovers`
entries are keyed on it, and a rebuilt node joins under it. What any node is
allowed to reach is the tailnet's policy, described in
[Tailnet policy](#tailnet-policy).

Re-authenticating this node after a rebuild ([`tofu-migration.md`](../../projects/tofu-migration.md))
needs an auth key created out of band, and a rebuilt node is a new device.
[ADR 0097 (Tailscale node configuration)](../../decisions/0097-how-a-tailscale-node-is-configured/revision-000.md)
decides that the key is single-use, tagged and supplied at run time, and
that the tag and the route's auto-approval are entries in the policy, which
already holds both ([Tailnet policy](#tailnet-policy)). The role itself is
described under [Tailscale node configuration](#tailscale-node-configuration).

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
   (`tag:subnet-router` in the host's variables)
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
| Subnet router (VM 202) | `tag:subnet-router` | None |
| Proxmox node, joined by hand, no approved route | None | Off, since an expired key drops the way to the hypervisor when the router VM is broken |
| Maintainer laptop | None | The domain's default |
| Maintainer phone and tablet, backup clients for when the laptop is out of reach, with the laptop's access | None | The domain's default |

**Policy sections.**

- `hosts` names the laptop, phone, tablet, Proxmox node and router by their tailnet addresses, so a grant and a test read by role. Re-adding a device gives it a new address, which is then updated here.
- `tagOwners` lets the maintainer apply `tag:subnet-router`, and `autoApprovers` approves `192.168.20.0/24` for a node carrying it. The router carries the tag.
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

Build it the way `tailscale` is built: declare its module and `ansible_hosts` entry in
the root module, list it under `network_infra` in `inventory.yaml` with no address,
and run the inventory generator
([`vm-provisioning.md`](vm-provisioning.md#tofu--ansible-handoff)). The host then
has a generated address, a generated host zone record and the admin user the
module sets. `ansible_python_interpreter` is a global default in `inventory.yaml`'s
`all.vars`; confirm it exists on the host, or override it per host, before the first
run.

## Verifying

```sh
ansible-playbook playbooks/maintenance.yaml --limit patched_hosts,localhost
```

Runs `apt`/`fwupd` against every `patched_hosts` member,
`qemu_guest_agent` against `network_infra` only, and then the
`host_hardening` baseline against every `patched_hosts` member. No
`deploy.yaml` equivalent exists for this group — see "Why its own group"
above.
