---
id: PROJ-opnsense-config
title: OPNsense Gateway Configuration
type: project
status: building
blocked: false
summary: The OPNsense gateway's policy, NAT, DNS forwards and DHCP brought under Ansible through its API from a minimal seed, then the coding-agent zone and its proxy.
decision: ADR-0089/0
super_project: tofu-vm-provisioning
track: opnsense
---

# OPNsense Gateway Configuration

Brings the OPNsense gateway's configuration under code, so the rules that are the network boundary are reviewed as code and the gateway can be rebuilt from nothing. A minimal seed that Tofu attaches sets what the API cannot, and the Ansible collection applies the rest ([ADR 0089 (OPNsense configuration)](../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md)). It builds on Tofu's root module and credentials file ([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#tofu-project)). Only its last stage waits for [`tofu-migration.md`](tofu-migration.md); the rest runs on a scratch gateway in that project's isolated block. DNS records for Tofu-provisioned VMs come from the `bind9` role ([`bind9.md`](../topics/services/bind9.md#the-host-zone)).

## Scope

The seed image and its attachment to the OPNsense module, the Ansible role that applies the gateway's configuration, and the policy, NAT, Unbound forwards and Kea scratch network it holds for the existing zones. Then the coding-agent zone's interface and rules ([`coding-agent-network.md`](coding-agent-network.md)) and egress-proxy configuration ([`coding-agent-egress.md`](coding-agent-egress.md)), with drift detected by the play's check. Not in scope: Phase 1 (VM shell and ISO), in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md#opnsense), DNS for Tofu-provisioned VMs ([`bind9.md`](../topics/services/bind9.md#the-host-zone)), and changing any policy the other decisions set.

## Decision

Implements [ADR 0089 (OPNsense configuration)](../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md), `approved` once its assumptions were resolved. Stages 4 and 5 also carry out the last bullet of [ADR 0053 (Coding-agent network reach)](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md)'s Decision, which becomes `accepted` when the network project completes.

The pinned pair is OPNsense 26.1.11 and the `oxlorg.opnsense` collection at commit `5cec92ea25c8280a9913dfb958109f78ce930d00`, whose `galaxy.yml` reads version 26.1.11. The collection's git tag `26.1.11` carries an earlier version's metadata, so the pin is the commit. The pair lives in the `opnsense_gateway` role's defaults, and `ansible/requirements.yml` installs the collection from git at the same commit. The mirror reports the 26.1 series as end of life, and 26.1.11 is its last release. The pair stays there: a move to 26.7 with a matching collection release is a release change, rehearsed on a scratch clone as the ADR's Validation describes, after the policy is written.

The seed builder and the script that answers the importer at the first boot are in the module's directory ([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#opnsense)). The scratch gateway is built by `tofu/scratch/opnsense/scratch_gateway.sh` ([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#opnsense)), which applies the OPNsense module with Tofu from the operator host, runs the first-boot script and updates the gateway. Its LAN NIC attaches to an isolated bridge with no physical port (`vmbr9`, which a run needs created, with `SDN.Use` granted to the token's user, since the token has no privilege separation), because the seed's LAN serves DHCP and must not share a bridge with real ports; the script refuses a LAN bridge that has one. Its WAN NIC attaches untagged to `vmbr1`, or tagged with `WAN_VLAN_ID`, where the production gateway's DHCP gives it an address and a route out. Do not give a scratch gateway the production WAN bridge.

A gateway built from the 26.1.6 `nano` image updated through its own API to 26.1.11 (core 26.1.11_10) in one update with one reboot. Afterwards the seeded API key still authenticated and a wrong secret was still refused, over the pinned certificate; the serial console showed a login prompt; and a package that was not installed installed and removed. The API's `product_latest` listing said 26.1.7 while the repository held 26.1.11, so the update list, not that listing, says where an update lands. A gateway that is behind its repository refuses a package install, so the update comes first. The live `config.xml` is not readable through the API (the backup download serves the newest saved backup), so no before and after hash of it was taken.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike on a scratch OPNsense in the isolated block: the seed's first-boot import, the API user and its key, the collection's coverage, savepoint revert, the gateway certificate, Unbound forwards, the unattended install | Done | Each assumption in ADR 0089 is resolved and folded into its Context, and the revision can be `approved` |
| 2 | The seed image and the Ansible role's skeleton. Starts from Tofu's root module and credentials file | Done | A scratch gateway builds from the seed, and the play's `--check --diff` reports no change after it converges |
| 3 | Policy, NAT, Unbound forwards and the Kea scratch network for the existing zones, with the hardening baseline | Done | `--check --diff` reports no change, and the flow list's probes ([`network-boundary-checks.md`](network-boundary-checks.md)) confirm the allowed flows work and the others fail |
| 4 | The coding-agent zone's interface and rules. Starts once [`coding-agent-network.md`](coding-agent-network.md) has built and documented the zone | Not started | `--check --diff` reports no change, and the zone's flows in the flow list pass |
| 5 | The egress proxy's configuration. Starts once [`coding-agent-egress.md`](coding-agent-egress.md) has built the proxy | Not started | The proxy's allowlist is generated from one source in the repo |
| 6 | Rebuild the production gateway (VM 201) from the seed and apply the play, after [`tofu-migration.md`](tofu-migration.md)'s cutover of the Ubuntu hosts. Retire the hand-maintained state and decommission the old VM | Not started | The topic doc describes the repo as the owner of the gateway's configuration, the old VM is decommissioned, and canary probes still pass |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [x] A scratch gateway builds from the seed, and the play's `--check --diff` reports no change once it has converged.
- [x] The policy, NAT, Unbound forwards and Kea scratch network for the existing zones are expressed in the play, and the flow list's probes confirm every allowed flow works and every other fails.
- [ ] The coding-agent zone's interface, rules and proxy configuration are expressed in the play, and the canary probes from [`coding-agent-egress.md`](coding-agent-egress.md) still pass after the cutover.
- [ ] The proxy's allowlist is generated from one source in the repo.
- [ ] The production gateway is rebuilt from the seed, the old VM is decommissioned, and the topic doc names the repo as the owner of its configuration.
- [ ] The API credential is held only in the credentials file ADR 0048 decides.

## Risks

- The hand-built rules stay authoritative until Stage 6, and drift until then.
- The collection works only with the OPNsense release of the same version, so the gateway's release waits for the collection's.
- The pinned series no longer gets fixes once it is end of life, so the move to 26.7 is a later release change, not an option to skip.
- A play applied to the live gateway changes live rules, so it runs with `--check --diff` first and the gateway VM is snapshotted before each apply.

## Existing-zone policy (draft)

The policy for the existing zones is written from the flows below, default-deny between VLANs, and replaces the hand-built rules instead of importing them. Each row names where it comes from; a row marked *confirm* rests on an answer from the maintainer or a document not yet read for it, and a row marked *written but off* is in the play with `enabled: false` until its owner settles the fact it rests on. Enabling it is a one-line change in the role's defaults, and the scratch run's probe plan follows the flows. This section becomes the first entries of the flow list of [`network-boundary-checks.md`](network-boundary-checks.md) once its schema exists, and is deleted with this project.

Traffic between two hosts on the same VLAN is switched on the bridge and never reaches the gateway, so it needs no rule: the five hosts on VLAN 20 reach each other (backups to SeaweedFS, OpenBao on 8200, Beszel agents to the hub, Gatus pushes, DNS between the zone servers) without one. Only flows that cross a VLAN, reach the gateway itself or leave through the WAN are listed.

| # | From | To | Port | Why | Source |
| :-: | :--- | :--- | :--- | :--- | :--- |
| 1 | Every VLAN | The gateway's address on that VLAN | DNS 53 tcp and udp, NTP 123 udp, ICMP echo; DHCP where Kea serves the VLAN | The VLANs' one resolver and time source; Kea's own firewall rules cover DHCP | ADR 0040, ADR 0089 |
| 2 | Operator host (VM 401 now, VM 302 later) | The gateway's address | 443 (API and GUI), 22 | The play, and the guard rule that comes first | ADR 0089 invariants |
| 3 | CD agent (VM 303, `192.168.30.3`) | The gateway's address | 443 | CD workflows apply the gateway's play | Maintainer. Written but off (`opnsense_gateway_cd_agent_management` is false) until the CD agent runs and ADR 0089's conditions for admitting it are met; owner [`cd-agent.md`](cd-agent.md) |
| 4 | Operator host | VLAN 20 hosts | 22 | Ansible plays | `inventory.yaml` |
| 5 | Operator host | `security` | 8200 | AppRole login and secret fetch | `secrets` role, `secrets-and-credentials-flow.md` |
| 6 | Operator host | `storage` | 443 | Tofu state and restore discovery | ADR 0058, `backup-and-restore-data-flow.md`. Written but off (`enabled: false`) until the remote state backend's port is decided; owner [`tofu-migration.md`](tofu-migration.md), which enables it in the change that settles the port |
| 7 | Operator host | VM 303 | 22 | `playbooks/cd-agent.yaml` | `inventory.yaml` |
| 8 | Operator host | VLAN 70 host | 22 | Provisioning the coding-agent host | ADR 0053 |
| 9 | Operator host | The node's WAN-side address | 8006, 22 | Tofu's API calls, and the first-boot script's SSH. The node is not on any VLAN: it is reached through the gateway's outbound NAT | Maintainer |
| 10 | CD agent | VLAN 20 hosts | 22 | Deploys | Written but off until the CD agent's approles are settled against ADR 0044; owner [`cd-agent-approles.md`](cd-agent-approles.md) |
| 11 | CD agent | `security` | 8200 | AppRole login | Written but off, as row 10 |
| 12 | CD agent | `storage` | 443 | Rotated write key for `redeploy-storage` | `cd-agent-host.md`. Written but off, as row 10; it also waits for the remote state backend's port when the key serves the state bucket |
| 13 | Tailscale subnet router (VLAN 20) | VLAN 70 host, VM 302 | 22 | The maintainer's route to those hosts from outside the lab, source-NATed to the router's address | ADR 0053, ADR 0058 |
| 14 | VLANs 20, 40 and 60 (the experimental block with Internet) | WAN | Any, except direct DNS on 53 and 853 | Registries, package mirrors, Caddy's DNS challenge, cloud targets, Telegram, Tailscale | ADR 0089 baseline. The destinations are not enumerated |
| 15 | VLAN 30 | WAN | Any, for now, except direct DNS as in row 14 | ADR 0058 wants only the proxy's allowlist here, and the proxy does not exist yet | ADR 0058, [`coding-agent-egress.md`](coding-agent-egress.md) |
| 16 | VLAN 40 desktops (the VM 4XX hosts) | `play` | 25565 | Minecraft clients | Maintainer |
| 17 | VLAN 40 desktops | `services` | 1688 | KMS activation | Maintainer |

Not on the list, so denied: any flow from VLAN 70 to another zone (ADR 0053), from VLAN 50 (the experimental block without Internet) and VLAN 60 to another zone or, for VLAN 50, to the WAN, and from any zone to the gateway's management ports other than rows 2 and 3.

The VLAN scheme gives one VLAN per VMID hundred, so the experimental block with Internet is the 6XX range (VLAN 60, `192.168.60.0/24`) and the coding-agent zone is the 7XX range (VLAN 70, `192.168.70.0/24`). VLAN 50 keeps the isolated experimental hosts.

Outbound NAT stays in automatic mode, which the seed sets, so the play writes no NAT rules: every zone's traffic to the WAN leaves with the gateway's WAN address, which is how the operator host reaches the Proxmox node. There is no inbound forward. An Internet rule passes a zone's traffic to everything outside the private ranges, so a zone cannot reach another zone or the node through it.

Hosts that reach `services` through the Tailscale subnet router (VM 202, `192.168.20.2`) share VLAN 20 with it and need no rule, and neither do remote players reaching `play` the same way. Rows 16 and 17 are the only inbound flows across a VLAN.

The untagged `lan` network (`192.168.0.0/24`, with its own DHCP range) retires as a zone. It was the old non-DDNS desktop network, also used for Windows template setup and other experiments, and its hosts move to VLAN 50 when they need no Internet and to VLAN 60 when they do (the template setup is the second). The gateway's untagged interface stays, because the VLAN devices sit on it, but it serves no hosts and the play writes no DHCP range or rules for it.

## Open items

- Whether the proxy's allowlist is generated by the gateway's play or by its own role, which depends on where the proxy runs ([`coding-agent-network.md`](coding-agent-network.md)'s Stage 1).
- [`vm-provisioning.md`](../topics/infra/vm-provisioning.md)'s OPNsense section ties all of Phase 2 to the VMID→IP mapping. It changes when Stage 2 lands, since DNS records are the only part that needs the mapping.
- The live gateway (VM 201) is an `i440fx` machine with SeaBIOS and an 8 GB disk, while the OPNsense module builds `q35`. Settle which the rebuilt gateway uses before Stage 6.
- How the operator host resolves the management name. The play checks that it does, and a renewal of the certificate (every 397 days) is noticed by the play's failed authentication.
- Whether [ADR 0048 (Tofu credentials)](../decisions/0048-where-tofu-credentials-live/revision-000.md) needs a revision, now that the play reads the OPNsense API key and secret from its credentials file, and that the CD agent's toolchain installs a collection from git.
- Connections from the workstation to the Proxmox API dropped now and then during spike runs (an upload closed mid-transfer, a VM create answered with an empty reply), and later three tries in a row of the 3 GB image upload failed with a closed connection. The scratch gateway's script now has the node download and unpack the image once, so no run uploads it. The cause of the drops is not found, the seed and the other uploads still go through the API, and the module has no retry of its own.
- Which credential takes the snapshot [ADR 0089 (OPNsense configuration)](../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md) requires before each apply. The Proxmox token in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md#proxmox-api-token) holds no snapshot privilege. The leading option is a token of its own, scoped to the gateway VM, that can create and delete snapshots but not roll back, kept with the play's other credentials in the file ADR 0048 decides because the play runs when OpenBao may be unreachable behind the gateway it changes. A rollback stays a person's act, and a CD agent job could hold the token later.
- How a clean `--check --diff` is judged, for what a run on a scratch gateway has not shown. The run applied and then checked ten modules (user, alias, rule, nat_source, unbound_general, unbound_forward, dhcp_general, dhcp_subnet, interface_vlan, package) on a gateway built from the seed at 26.1.11. Every check after the module's own apply reported no change, including the two that name every setting, so a clean check is that no task reports changed, with no allow-list for these modules. After a change made behind the module's back, nine of the ten reported the changed value (the user module's diff is hidden by `no_log`, but its task reports changed), and a second apply converged each. Three things are left. Package locks, anything set through the generic call, and a user password set to `always` were not exercised, and the settings only the seed sets are never reported, so Stage 3 settles each by leaving the object out of the check unless it can be reported cleanly. A forward whose target is changed behind the module's back is not reported by the module, which has no argument to match on the domain alone, so the play reads the gateway's forward list and removes every forward it does not write, and `--check` shows that removal as a change. The alias diff carries a `url_auth_type` line only when the alias changed. The raw outputs are not committed; the kit that captured them lives outside the repo.
- Rows 1 to 7 and 9 to 17 of the draft policy are in the play (zone aliases, the guard rule, DNS, NTP and ping to the gateway, the flows between zones, and each zone's Internet access with direct DNS denied), and Kea's scopes for the desktops, isolated and experimental zones with them. A scratch gateway at 26.1.11 showed that `(self)` as a destination matches the gateway's own addresses, that the guard rule is evaluated before a floating block rule that follows it, that DNS, NTP and ping reach the gateway from a host in each zone, that automatic outbound NAT covers every zone with Internet access, that every source and listener pair agrees with the flows, and that Kea answers in each zone it serves, the reserved address included. The sample configuration's dnsmasq holds UDP port 67 for the LAN, which keeps Kea from opening its sockets, so the play turns it off. Rows 6, 10, 11 and 12 are written but not in force, because each is marked *confirm*; row 8 and the VLAN 70 half of row 13 wait for that zone's stage. Unbound forwards the host zone and the lan zone to both DNS servers, and the zones are set as `-e` variables (`opnsense_gateway_forward_domains`) because they derive from the main domain, which the play does not read. A scratch gateway showed that a host in two zones resolves a name in each forwarded zone through the gateway from either server's answer, and that a forward the play does not write is reported by `--check`, removed by a run and gone from the next check. The guard rule's source is a required list, and VM 401 takes its address from DHCP, so it needs a reservation before it can be listed: an entry in `opnsense_gateway_dhcp_reservations` (zone `desktops`, an address outside the pool such as `192.168.40.250`, and its MAC) and the same address in `opnsense_gateway_operator_hosts`. The play reads both as `-e` variables, and neither is in the repo.
- The hardening baseline in [ADR 0089 (OPNsense configuration)](../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md) is applied. Direct DNS out of the VLANs is denied by the play. The seed turns IPv6 off, puts a one-time password in front of the GUI login and gives the API user six privileges instead of `page-all`. A scratch gateway at 26.1.11 showed that the GUI refuses a password alone, a wrong code and the code after the password, and accepts the code in front of it; that the play, the update and the diagnostics work with the narrowed API key, which is refused user management, Unbound and the service list; and that the first boot and the update work against the unlocked console menu, which the seed leaves unlocked because a console login would need the code too. That no IPv6 rule remains in the gateway's firewall has not been looked at. SSH is key-only whenever it is turned on, since the sample sets neither password authentication nor root login, and the seed leaves the service off; a test pins both. The privileges match a path only by the spelling in the gateway's privilege table, so a test checks every API path the repo calls against it; the Unbound forwards will need their own privilege.
- Which hosts still sit on the untagged `lan` and which of VLAN 50 or 60 each moves to. Moving them changes their addresses, so the DNS records and any static leases that name them move too.
- Nothing is built on VLAN 60 or VLAN 70 yet. VLAN 60 changes hands from the coding-agent zone to the experimental block with Internet, so the unbuilt zone's documents were moved to VLAN 70 and VMID 701 with it.

## The production rebuild

What the rebuild of VM 201 needs, collected here so the cutover does not rediscover it. It follows [`tofu-migration.md`](tofu-migration.md)'s cutover of the Ubuntu hosts.

- **Rehearsal.** A scratch gateway built from the same seed and the same play, with the same `-e` variables, passes the kit's run (every probe, `--check` clean, the stale-forward round trip) before the production gateway is touched.
- **Rollback.** The old VM is dumped (`vzdump`) before it is destroyed, because the module derives the NIC MACs from the VMID and the rebuilt gateway must be VMID 201 to keep them. A rollback is a restore of that dump, which keeps the old MACs and so the hosts' neighbour tables.
- **Variables.** `opnsense_gateway_operator_hosts`, `opnsense_gateway_forward_domains` (the host zone and the lan zone, from the main domain), the CA file the first boot reads off the console, and the credentials file holding the root password, the API key and secret and root's OTP seed (ADR 0048).
- **VM 401.** It takes its address from DHCP on the untagged `lan` today and moves to VLAN 40. In `opnsense_gateway_dhcp_reservations` it is `{ name: vm401, zone: desktops, address: 192.168.40.250, mac: <its NIC's MAC> }`, and `192.168.40.250` is in `opnsense_gateway_operator_hosts` until VM 302 takes over. The MAC `bc:24:11:00:01:91` is the Tofu scheme's for VMID 401 and is what the scratch run used; read the real one from the VM's hardware before relying on it. The guard rule admits only the zone interfaces, so VM 401 reaches the rebuilt gateway's management over the untagged `lan` for the first apply and loses that path when its NIC tag is set to 40. The order is therefore: rebuild the gateway, apply the play from VM 401 on the untagged `lan`, set the NIC tag to 40, renew the lease and check the gateway answers on 443 from `192.168.40.250`. A static `192.168.40.250` set in the guest before the tag change avoids waiting for the lease. The Proxmox console is the way in if it does not. Whether the sample's own rules for the untagged `lan` remain on the rebuilt gateway was not looked at.
- **Machine type.** The live gateway is `i440fx` with SeaBIOS and an 8 GB disk, and the module builds `q35`: settle which the rebuilt gateway uses.
- **Operator host.** It resolves `OPNsense.internal` to the gateway (the certificate renews every 397 days and a failed authentication notices it).
- **Hosts on the untagged `lan`.** Which of VLAN 50 or 60 each moves to, with their DNS records and static leases.
- **Later applies.** The snapshot credential ADR 0089 requires before each apply (a token scoped to the gateway VM that can create and delete snapshots but not roll back), and whether the CD agent applies the play ([ADR 0089 (OPNsense configuration)](../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md)'s conditions).

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
