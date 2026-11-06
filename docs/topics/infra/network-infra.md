# Network Infrastructure Hosts

Hosts that support the network itself rather than running Docker/compose apps: the
`network_infra` inventory group. Currently one host, `tailscale` (VM 202), the
Tailscale subnet router. What the router lets a tailnet device reach is the
[tailnet policy](tailnet-policy.md).

## Why its own group, not `managed_hosts`

`managed_hosts` gets Docker, the `compose`/`compose_app` roles, and every app-deploy
play in `deploy.yaml`. VM 202 runs none of that — it is a routing appliance, not an
app host — so folding it into `managed_hosts` would mean either deploying Docker to a
VM that has no use for it, or complicating every `deploy.yaml` play with a new
exclusion.

| Group | Targeted by | Notes |
| :--- | :--- | :--- |
| `network_infra` | `network-infra.yaml`, `maintenance.yaml` | Stays out of `deploy.yaml` entirely |
| `patched_hosts` | `maintenance.yaml` | An alias of `managed_hosts` + `network_infra`, the same pattern as `app_hosts` ([`ansible.md`](../deploy/ansible.md#inventory)) |

## Built by Tofu

`tailscale` is a Tofu-provisioned VM at VMID 202, declared in the root module like the
app hosts. The inventory generator
([`vm-provisioning.md`](vm-provisioning.md#tofu--ansible-handoff)) supplies its address
and login user, so `inventory.yaml` keeps only its group membership, and its host zone
record is generated from that address ([`bind9.md`](../services/bind9.md#the-host-zone)).
[Rebuilding it](../disaster-recovery/rebuild-runbook.md#tailscale) needs an auth key
created out of band, and a rebuilt node is a new device.

## `tailscale` (VM 202)

What the Tofu module and the role leave on the host.
`rebuild_check.host tailscale` checks the address, forwarding, tag, approved route and
key expiry ([the checks](../disaster-recovery/rebuild-tools.md#rebuild_checkhost)).

| Field | Value |
| :--- | :--- |
| OS | Ubuntu LTS (`resolute`) |
| Tailscale | Installed by the `tailscale_node` role from Tailscale's apt repository ([node configuration](#tailscale-node-configuration)); `tailscaled.service` active |
| Role | Subnet router: advertises `192.168.20.0/24`, and `PrimaryRoutes` in `tailscale status --self --json` holds it once the policy has approved it |
| Tag | `tag:subnet-router` (`Tags` of `Self` in `tailscale status --self --json`). The policy's `tagOwners` and `autoApprovers` entries are keyed on it, and a rebuilt node joins under it |
| Host zone name | `tailscale.{{ host_domain }}`, a record the `bind9` role generates from the host's address |
| LAN address | `192.168.20.2/24`, static from cloud-init, the address VMID 202 derives ([scheme](vm-provisioning.md#vmid--vlan--ip-scheme)); it needs no reservation on the gateway, and the gateway's flows name it, so a rebuilt VM keeps it. The host is in `sos-inventory.yaml` with that address, the DNS-independent list `reset-network.yaml` uses when DNS itself might be down |
| SSH admin user | `tsadmin` |
| `qemu-guest-agent` | Applied to the group by `maintenance.yaml` |
| Client preferences | Set by the role: the advertised routes, the accepted DNS setting and the client's auto-update off |
| Forwarding | `net.ipv4.ip_forward` and `net.ipv6.conf.all.forwarding` are 1 and set in `/etc/sysctl.d/99-tailscale.conf` |
| Service files | `tailscaled.service` and `/etc/default/tailscaled` are the package's (`PORT="41641"`, `FLAGS=""`) |
| Key expiry | None: `KeyExpiry` of `Self` in `tailscale status --self --json` is null |
| Availability | Not always on while spike VMs share the node and VM 401 is in service; always on once the operator host and the laptop replace VM 401, since every operator session then crosses it ([ADR 0097](../../decisions/0097-how-a-tailscale-node-is-configured/revision-000.md)) |
| Updates | `unattended-upgrades` takes security origins only and its local override only removes unused packages, so Tailscale's repository is outside it. `maintenance.yaml` is what upgrades the package, since the role turns the client's own updater off |
| Host firewall | `tailscaled`'s own rules accept everything that arrives on `tailscale0`, so the tailnet policy decides what a tailnet source reaches on the node itself |

## Tailscale node configuration

`playbooks/network-infra.yaml` applies the `tailscale_node` role to the group
([ADR 0097](../../decisions/0097-how-a-tailscale-node-is-configured/revision-000.md)),
which decides that the join key is single-use, tagged and supplied at run time, and
that the tag and the route's auto-approval are entries in the
[policy](tailnet-policy.md), which already holds both. The role converges, in order:

| # | Step | What it does |
| :-: | :--- | :--- |
| 1 | Install | Tailscale's apt repository as a DEB822 source with its key in `/etc/apt/keyrings/tailscale.gpg`, installed only if the download is the pinned key ([`apt-signing-keys.md`](../deploy/apt-signing-keys.md)); the vendor script's one-line `tailscale.list` removed in the same run; the package installed and never upgraded; `tailscaled` enabled and started. Only `maintenance.yaml` upgrades the package |
| 2 | Forwarding | `/etc/sysctl.d/99-tailscale.conf` sets IPv4 and IPv6 forwarding when the node advertises routes. A node that advertises none has no such file: the role removes one left by an earlier run and turns both forwarding values off in the same run |
| 3 | Join, only when the node is logged out | Needs `tailscale_node_tag` (`tag:subnet-router` in the host's variables) and a key; a logged-out node missing either stops the play before anything changes. A logged-in node needs neither |
| 4 | Preferences | Compared against `tailscale debug prefs` and applied with one `tailscale set` for the ones that differ: the advertised routes (`tailscale_node_advertise_routes`), the accepted DNS setting (`tailscale_node_accept_dns`, on by default) and the client's auto-update, which is off on every node. Source NAT is left at the client's default |

The join key is single-use, pre-authorized, tagged and valid for hours, made in the
admin console for the run. It is read from `TAILSCALE_AUTHKEY` on the operator's
machine, passed as one argument of the join command and kept out of the play's
output; it is written to no file.

```sh
cd ansible
ansible-playbook playbooks/network-infra.yaml --limit tailscale,localhost -e network_infra_check=true --diff
read -rs TAILSCALE_AUTHKEY; export TAILSCALE_AUTHKEY   # only to join a logged-out node
ansible-playbook playbooks/network-infra.yaml --limit tailscale,localhost
unset TAILSCALE_AUTHKEY
```

A check run changes nothing, and is asked for with `-e network_infra_check=true`
because `--check` also puts the secrets play in check mode, which fails. It reports
the `tailscale set` call a real run would make, so a preference changed by hand on the
node shows up there. On a node installed by the vendor script, the first run replaces
its one-line apt source and turns the client's auto-update off.

### Adding a route

Add the CIDR, in the canonical form the node reports it in, to
`tailscale_node_advertise_routes` in `inventory/host_vars/tailscale.yaml`, after
[its grant and auto-approval](tailnet-policy.md#adding-a-grant-for-a-route) are saved
in the tailnet policy. The next run calls `tailscale set`.

## Bringing a new `network_infra` host under management

Build it the way `tailscale` is built:

1. Declare its module and `ansible_hosts` entry in the root module.
2. List it under `network_infra` in `inventory.yaml` with no address.
3. Run the inventory generator ([`vm-provisioning.md`](vm-provisioning.md#tofu--ansible-handoff)).

The host then has a generated address, a generated host zone record and the admin user
the module sets. `ansible_python_interpreter` is a global default in
`inventory.yaml`'s `all.vars`; confirm it exists on the host, or override it per host,
before the first run.

## Verifying

```sh
ansible-playbook playbooks/maintenance.yaml --limit patched_hosts,localhost
```

Runs `apt`/`fwupd` against every `patched_hosts` member, `qemu_guest_agent` against
`network_infra` only, and then the `host_hardening` baseline against every
`patched_hosts` member. No `deploy.yaml` equivalent exists for this group.
