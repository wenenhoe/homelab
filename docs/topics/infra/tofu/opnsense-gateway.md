# OPNsense gateway play

The Ansible play that writes the gateway's configuration through its API, after the
[VM](opnsense-vm.md) has first-booted from its seed. The gateway is not an Ansible
host: every call is to its API at `OPNsense.internal`, from the operator host.

```sh
ansible-playbook playbooks/opnsense.yaml --check --diff -e opnsense_gateway_ca_file=PATH
```

`PATH` is the `gateway-cert.pem` the [first-boot script](opnsense-vm.md#first-boot)
wrote: the only CA the play trusts. The operator host must resolve
`OPNsense.internal`. The play is `playbooks/opnsense.yaml` with the
`opnsense_gateway` role ([`ansible.md`](../../deploy/ansible.md)).

## Variables the play needs

| Variable | Why |
| :--- | :--- |
| `opnsense_gateway_ca_file` | The certificate to pin |
| `opnsense_gateway_operator_hosts=[...]` | The IPv4 addresses the work runs from. The play stops without it, since an empty guard rule would admit nobody, and stops when the address it reaches the gateway from is not in it (`-e '{"opnsense_gateway_operator_not_listed_ok":true}'` overrides that when NAT or a tunnel changes the address the gateway sees) |
| `opnsense_gateway_forward_domains=[...]` | The host zone and the lan zone, which derive from the main domain. The play stops without them |
| `opnsense_gateway_cd_agent_management` | The CD agent's rule is written only when this is true, and removed when it is false |
| `opnsense_gateway_dhcp_reservations=[...]` | Each reserved host's `name`, `zone`, `address` and `mac`, in a Kea zone and outside its pool. A host that takes its address from DHCP needs one before it can be named in `opnsense_gateway_operator_hosts` (the operator host does). Neither list is in the repo |

A list or a boolean goes in as JSON (`-e '{"name":true}'`): `-e name=true` passes the string
`"true"`, which a conditional of the role refuses.

`--check` on a gateway the play has never applied cannot finish: it creates nothing, so a
reservation reports that its Kea subnet is not found. Apply once, then `--check` reports
no change.

## Pre-checks

Before anything else the role checks:

1. The credentials file (mode `0600`, holding `opnsense_api_key` and
   `opnsense_api_secret`).
2. That the installed `oxlorg.opnsense` collection is the pinned release.
3. That `OPNsense.internal` resolves.
4. That the seeded key authenticates over the pinned certificate. A renewed GUI
   certificate fails this until the console is read again.
5. That the gateway runs the pinned release. The check asks the gateway for its
   firmware status, which probes the OPNsense mirror, so the gateway needs its route
   out.

The release and the collection's commit are the role's defaults;
`ansible/requirements.yml` installs the collection from git at the same commit, and
a test fails when the two differ.

## What it writes

| Object | Content |
| :--- | :--- |
| Aliases | One per zone's network; one for the operator hosts, the CD agent and the gateway's management ports |
| Guard rule | A floating quick pass at sequence 1 admitting the operator hosts to the gateway's SSH and API ports |
| Per-zone rules | DNS, NTP and ping to the gateway |
| Flows | The flows between zones in `opnsense_gateway_flows`: a pass rule on the source zone's interfaces, each matched by its name. One marked `enabled: false` is written but not in force |
| Internet zones | A zone marked `internet: true` also gets a rule denying direct DNS (ports 53 and 853) to anything but the gateway, and one passing its traffic to everything outside the private ranges. Other zones reach only the flows listed |
| Other rules | Removes any rule the gateway's API lists that the play does not write, matched by description, which `--check` reports as a change. What the play writes is every rule above, including a flow marked `enabled: false` and excluding one its switch turns off. The guard rule is one it writes, so it is never removed. The legacy rules the seed holds (the bootstrap rule) are not listed by the API and are outside this. A rule with no description stops the play, as it cannot be named to remove |
| NAT | Outbound NAT is left in the automatic mode the seed sets |
| Kea | On for zones marked `dhcp: true` (desktops and the two experimental blocks, whose clients Tofu does not place), each with a scope of `192.168.<vlan>.10` to `.245`. Keeps the reservations in `opnsense_gateway_dhcp_reservations` (`name`, `zone`, `address`, `mac`), which must sit in a Kea zone outside the pool. A zone not marked is left alone |
| Unbound | Forwards the host zone and the lan zone to the two DNS servers (`opnsense_gateway_forward_servers`, `192.168.20.3` and `192.168.20.6`). Removes any forward it does not write, which `--check` reports as a change |

## Zone policy

The repository owns the gateway's configuration: the policy below is written from the flows
the lab's decisions require, default-deny between VLANs, and replaces the hand-built rules
instead of importing them. A row marked *written but off* is in the play with `enabled: false`
until its owner settles the fact it rests on, which is a one-line change in the role's
defaults. The flows a canary can try from a zone are in the flow list of
[`network-boundary-checks.md`](../network-boundary-checks.md), and its probes follow the flows.

Traffic between two hosts on the same VLAN is switched on the bridge and never reaches the
gateway, so it needs no rule. Only flows that cross a VLAN, reach the gateway itself or leave
through the WAN are listed.

A flow is known by its name in the first column, which other docs cite by a link to this section, as [`operator-gateway`](#zone-policy) does. The order of the rows carries no meaning, so a flow added or moved leaves every citation of another as it was. [The drift check](../../documentation/doc-checks.md#docs-drift-check) refuses a citation by number, and a linked name that is not in the table.

| Flow | From | To | Port | Why | Source |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `operator-gateway` | Operator host (VM 401 now, VM 252 later) | The gateway's address | 443 (API and GUI), 22 | The play, and the guard rule that comes first | ADR 0089 invariants |
| `cd-agent-gateway` | CD agent (VM 253, `192.168.25.3`) | The gateway's address | 443 | CD workflows apply the gateway's play | Maintainer. Written but off (`opnsense_gateway_cd_agent_management` is false) until the CD agent runs and a revision of ADR 0089 admits it once its conditions are met; owner [`cd-agent.md`](../../../projects/cd-agent.md) |
| `operator-vlan20-ssh` | Operator host | VLAN 20 hosts | 22 | Ansible plays | `inventory.yaml` |
| `operator-security` | Operator host | `security` | 8200 | AppRole login and secret fetch | `secrets` role, `secrets-and-credentials-flow.md` |
| `operator-storage` | Operator host | `storage` | 443 | Restore discovery | ADR 0058, `backup-and-restore-data-flow.md`. Tofu's state is held on R2, not `storage` ([ADR 0103](../../../decisions/0103-where-tofus-state-is-held/revision-000.md)), so only restore discovery needs it. Written but off (`enabled: false`) until the controller moves; owner [`operator-host-takeover.md`](../../../projects/operator-host-takeover.md), which enables it in that change |
| `operator-cd-agent-ssh` | Operator host | VM 253 | 22 | `playbooks/cd-agent.yaml` | `inventory.yaml` |
| `operator-vlan30-ssh` | Operator host | VLAN 30 host | 22 | Provisioning the coding-agent host | ADR 0053. Added to the play by [`coding-agent-network.md`](../../../projects/coding-agent-network.md) |
| `operator-node` | Operator host | The node's WAN-side address | 8006, 22 | Tofu's API calls, and the first-boot script's SSH. The node is not on any VLAN: it is reached through the gateway's outbound NAT | Maintainer |
| `cd-agent-vlan20-ssh` | CD agent | VLAN 20 hosts | 22 | Deploys | Written but off until the CD agent's approles are settled against ADR 0044; owner [`cd-agent.md`](../../../projects/cd-agent.md) |
| `cd-agent-security` | CD agent | `security` | 8200 | AppRole login | Written but off, as [`cd-agent-vlan20-ssh`](#zone-policy) |
| `cd-agent-storage` | CD agent | `storage` | 443 | Rotated write key for `redeploy-storage` | `cd-agent-host.md`. Written but off, as [`cd-agent-security`](#zone-policy); it also waits for the remote state backend's port when the key serves the state bucket |
| `tailscale-vlan30-ssh` | Tailscale subnet router (VLAN 20) | VLAN 30 host, VM 252 | 22 | The maintainer's route to those hosts from outside the lab, source-NATed to the router's address | ADR 0053, ADR 0058 |
| `internet-wan` | VLANs 20, 40 and 55 (the experimental block with Internet) | WAN | Any, except direct DNS on 53 and 853 | Registries, package mirrors, Caddy's DNS challenge, cloud targets, Telegram, Tailscale | ADR 0089 baseline. The destinations are not enumerated |
| `management-wan` | VLAN 25 | WAN | Any, for now, except direct DNS as in [`internet-wan`](#zone-policy) | ADR 0058 wants only the proxy's allowlist here, and the proxy does not exist yet | ADR 0058, [`coding-agent-egress.md`](../../../projects/coding-agent-egress.md) |

Not on the list, so denied: any flow from VLAN 30 to another zone (ADR 0053), from VLAN 50 (the experimental block without Internet) and VLAN 55 to another zone or, for VLAN 50, to the WAN, and from any zone to the gateway's management ports other than [`operator-gateway`](#zone-policy) and [`cd-agent-gateway`](#zone-policy).

The VLAN scheme gives one VLAN per block of 50 VMIDs ([`vm-provisioning.md`](../vm-provisioning.md#vmid--vlan--ip-scheme)), so the management zone is VMIDs 250 to 299 (VLAN 25, `192.168.25.0/24`), the coding-agent zone is 300 to 349 (VLAN 30, `192.168.30.0/24`) and the experimental block with Internet is 550 to 599 (VLAN 55, `192.168.55.0/24`). VLAN 50 keeps the isolated experimental hosts.

Outbound NAT stays in automatic mode, which the seed sets, so the play writes no NAT rules: every zone's traffic to the WAN leaves with the gateway's WAN address, which is how the operator host reaches the Proxmox node. There is no inbound forward. An Internet rule passes a zone's traffic to everything outside the private ranges, so a zone cannot reach another zone or the node through it.

Hosts that reach `services` through the Tailscale subnet router (VM 202, `192.168.20.2`) share VLAN 20 with it and need no rule, and neither do remote players reaching `play` the same way. The only inbound flows across a VLAN, the desktops' Minecraft and KMS flows, are in the flow list ([`network-boundary-checks.md`](../network-boundary-checks.md)), not in this table.

The untagged `lan` network (`192.168.0.0/24`, with its own DHCP range) retires as a zone. It was the old non-DDNS desktop network, also used for Windows template setup and other experiments, and its hosts move to VLAN 50 when they need no Internet and to VLAN 55 when they do (the template setup is the second). The gateway's untagged interface stays, because the VLAN devices sit on it, but it serves no hosts and the play writes no DHCP range or rules for it.

## Zones and interfaces

The seed assigns VLAN interfaces at the gateway's first boot only, in ascending order of VLAN:
20, 25, 30, 35, 40, 45, 50 and 55 are `opt1` to `opt8`, and the play names every zone's
interface by that order. A zone whose project has not landed has its interface and none of its
rules, until that project adds them to the play. A zone is never built by hand on the live
gateway: the play is applied to it, so a hand-built zone would be removed as drift.

- [`coding-agent-network.md`](../../../projects/coding-agent-network.md) adds VLAN 30 and the [`operator-vlan30-ssh`](#zone-policy)
  and [`tailscale-vlan30-ssh`](#zone-policy) flows.
- [`coding-agent-egress.md`](../../../projects/coding-agent-egress.md) adds VLAN 45, the egress
  zone, and generates the two proxies' allowlists from one source in the repo.
- VLAN 35, the DMZ, is in the play with its interface and the rules every zone gets; the rules for the host it will hold are still [`gatehouse.md`](../../../projects/gatehouse.md)'s to add.

## What a clean check means

A clean `--check --diff` is that no task reports changed, with no allow-list. On a gateway built
from the seed, every check after a module's own apply reported no change for the user, alias,
rule, outbound NAT, Unbound general, Unbound forward, Kea general, Kea subnet, VLAN interface and
package modules, including the two that name every setting. After a change made behind a module's
back, nine of the ten reported the changed value (the user module's diff is hidden, but its task
reports changed), and a run converged each.

- A forward the play does not write is not reported by the module, which has no argument to match
  on the domain alone, so the play reads the gateway's forward list and removes every forward it
  does not write. `--check` shows that removal as a change.
- The alias diff carries a `url_auth_type` line only when the alias changed.
- Package locks, anything set through the collection's generic call and a user password set to
  `always` were not exercised, so the play leaves such objects out of the check.
- A rule with no description stops the play instead of being removed, since it cannot be named.
  How the play would tell a rule it writes from one it must remove, if descriptions stop being
  enough, is an open question.

## What the check cannot see

The settings only the seed sets are not shown by the API, so a change to one is invisible to
`--check` and reaches a running gateway only by hand in the GUI: the hostname, time zone, SSH
service, the GUI's listen interfaces, NTP and anti-lockout. The legacy rule the seed holds on the
untagged LAN is not listed by the rule API either, so the play neither reports nor removes it
([the seed's note](opnsense-vm.md#seed-disk)). Unknown: whether any IPv6 rule remains in the
gateway's firewall, which has not been looked at. The drift check
([`opnsense-drift-check.md`](../../../projects/opnsense-drift-check.md)) carries these.

## What a scratch gateway showed

- `(self)` as a destination matches the gateway's own addresses.
- The guard rule is evaluated before a floating block rule that follows it, and DNS, NTP and ping
  reach the gateway from a host in each zone.
- Automatic outbound NAT covers every zone with Internet access, and Kea answers in each zone it
  serves, the reserved address included.
- The sample configuration's dnsmasq holds UDP port 67 for the LAN, which keeps Kea from opening
  its sockets, so the play turns it off.
- A host in two zones resolves a name in each forwarded zone through the gateway from either
  DNS server's answer.
- The GUI refuses a password alone, a wrong code and the code after the password, and accepts the
  code in front of it. The play, the update and the diagnostics work with the narrowed API key,
  which is refused user management and the service list, and the first boot and the update work
  against the unlocked console menu.
- SSH is key-only whenever it is turned on, since the sample sets neither password authentication
  nor root login, and the seed leaves the service off. A test pins both.
- The API privileges match a path only by the spelling in the gateway's privilege table, so a
  test checks every API path the repo calls against it, and the paths each collection module the
  role calls asks for. The test fails when the role calls a module its list lacks.

## Release changes

The OPNsense release and the collection's commit are a pair, pinned in the role's defaults and
`ansible/requirements.yml`, and the collection works only with the release of its own version, so
the gateway's release waits for the collection's. The mirror reports the 26.1 series as end of
life and 26.1.11 as its last release, so moving to 26.7 is a release change, not an option to
skip: it is rehearsed on a scratch clone first, as
[ADR 0089 (OPNsense configuration)](../../../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md)
describes, and production is then updated from a Proxmox snapshot.
