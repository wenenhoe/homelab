---
id: ADR-0089
revision: 0
type: adr
title: How the OPNsense gateway is configured
short: OPNsense configuration
solution: A minimal seed configuration for what the API cannot set, then an Ansible collection applies the rest from the operator host
summary: What defines the OPNsense gateway's configuration after first boot, which services it runs, and how a release change is made safe.
topic: deployment-platform
status: working
related: [ADR-0040, ADR-0048, ADR-0053, ADR-0058]
---

# 0089. How the OPNsense gateway is configured

## Problem

OPNsense is the lab's gateway, and its configuration is the network boundary that other decisions rely on. That configuration has to be reviewable as code, rebuildable from nothing, and safe to change when a release moves underneath it. It must also describe what the lab needs, not a copy of whatever a hand-built gateway accumulated.

## Context

- Tofu builds the gateway's VM shell with the `proxmox_opnsense_vm` module. The install and the day-2 configuration are manual ([`vm-provisioning.md`](../../topics/infra/vm-provisioning.md#opnsense)).
- Most OPNsense objects are configurable through its API. In the 26.1 series that API cannot assign a VLAN device to an interface or give the interface an address; the 26.7 series adds an assignment API.
- Tooling follows releases. The Ansible collection `oxlorg.opnsense` states that each of its releases works only with the OPNsense release of the same version. The Tofu provider `browningluke/opnsense` is pre-1.0, changes schemas between releases, and has no resource for interface assignment, system settings or packages.
- The collection can verify the gateway's TLS certificate against a CA file, but only when the name or address it connects to appears in that certificate. It has a generic call for endpoints it has no module for, and a savepoint action for firewall changes. At its 26.1.11 release it has modules for VLAN devices, firewall rules and aliases, outbound NAT, Kea subnets, Unbound forwards and settings, packages and users. It has none for system settings (its `system` module only powers off, reboots, updates, upgrades and audits) or for the gateway's own certificate, which go through the generic call. Its git tag `26.1.11` carries the metadata of an earlier version, so the pin is a commit.
- The API credential cannot live in OpenBao for the reason [ADR 0048 (Tofu credentials)](../0048-where-tofu-credentials-live/revision-000.md) gives: OpenBao sits behind the gateway being rebuilt.
- The maintainer reaches the VLANs through the Tailscale subnet router, which source-NATs, so every tailnet node arrives at the gateway with the router's address. Only the operator host ([ADR 0058 (Operator work host)](../0058-where-operator-work-runs/revision-000.md)) and, until it is retired, VM 401 can be told apart by source address.
- OPNsense imports a configuration only on install media: its importer waits for a key press at the console, then asks which disk to read, and the installer then clones the live system's `/conf` onto the target disk. A system that boots from a disk already holding `/conf/config.xml` skips the importer. Neither prompt has an unattended mode. Run from a shell with the disk name as its argument, the importer asks nothing. At boot the 26.1.6 source skips the key press whenever the root file system is writable and `/conf/config.xml` exists, so a disk that is already installed, including a pre-installed image, never offers the import. The API cannot restore a configuration either: its backup calls list, diff, download, delete and revert backups already on the gateway, and a whole file can be uploaded only on the legacy Diagnostics > Backups page.
- On 26.1.6 in a scratch VM, a second virtio-SCSI disk with an MBR partition table and one FAT partition holding `conf/config.xml` appears in the importer's device list as `da1`, and importing it restores the file. The installer carries it to the installed disk, which then boots without the importer prompt, with the seeded interface assignments, a root password that logs in to the GUI, and an API user whose key authenticates while a wrong secret is refused. OPNsense stores the API secret as a SHA-512 crypt hash, so the seed holds only the hash. After the import the install media's `installer` login no longer works, because the seed replaces the media's configuration. Tofu attached the seed through the gateway module, which uploaded it as import content and attached it as a second disk.
- Run against that gateway, the collection's modules for aliases, firewall rules and Unbound forwards created their objects, a second run and `--check` reported no change, and a change made in the GUI to an alias, a rule's port and a forward was reported as drift by the next `--check --diff` and repaired by a run. The alias diff carries an unrelated `url_auth_type` line, and the forward is reported as changed with no diff. The generic call applies nothing in `--check` and reports a change on every real run, so an object set through it never shows drift.
- The same run for users, Unbound general settings and Kea general settings created or matched their objects, reported no change on a second run and under `--check`, and reported a GUI change to a user's full name, to DNSSEC and to the Kea lifetime in the next `--check --diff`, with the right values, and a run repaired each. The Unbound and Kea modules write every setting they have and fill any a task omits from their own defaults: a task that named DNSSEC but not the DNS64 prefix also changed the prefix from empty to `64:ff9b::/96`, so a task names every setting. A password cannot be compared, so a user with `update_password: always` reports a change on every run and one with `on_create` does not. A user's diff carries a `membership` change from a list to an empty string beside the real one. Privileges are passed as the gateway's identifiers, such as `page-system-login-logout` for "Lobby: Dashboard", and a name the gateway does not know fails the call. The package module reports a change on every lock and every unlock, including one that finds the package already in that state, so its report cannot show drift for locks; installing an installed package changes nothing. A package that is not installed was not installed, because the scratch bridge has no route out.
- OPNsense has no API for the hostname, time zone, SSH, the GUI's listen address or certificate, NTP or the anti-lockout setting. The legacy pages own them, and the system API only halts, reboots and reports status. Only the seed or the GUI sets them, and `--check --diff` does not see them. The certificate API creates and imports certificates but cannot make one the GUI's.
- When the configuration names no usable GUI certificate, the 26.1.6 web GUI creates one at its start: a self-signed RSA 4096 certificate valid for 397 days whose subject name and only subject alternative name are the configuration's `hostname.domain`. The key is created on the gateway, so a seed that sets the hostname and domain and holds no certificate carries no key. Nothing renews the certificate; the console menu and `rc.restart_webgui renew` create a new one. The collection builds Python's default TLS context and loads the CA file into it. A certificate made with the same `openssl` command and configuration, loaded as that CA file, verified for its name on Python 3.12, 3.13 (whose default context is strict) and 3.14, and a connection by IP address, by another name, or without the file was refused. A play that verifies the certificate therefore connects by the management name, not an address. On the 26.1.6 scratch gateway the generated certificate named `OPNsense.internal`, the seed's hostname and domain, and was valid for 397 days. With that certificate as the only CA file and the name resolved to the gateway, the seeded API key was answered with HTTP 200, and the same call under another name was refused with a certificate error before any HTTP status.
- With anti-lockout on, the default, the gateway admits every host on its primary interface to the GUI and SSH ports, which contradicts the management invariant below. The setting is `noantilockout` in the configuration.
- Within a priority group, a rule created through the API for one interface is placed after the legacy rules of that interface, so a legacy allow rule such as the sample configuration's "allow LAN to any" is reached first and the rule after it never applies. A rule that lists several interfaces is floating and is evaluated before them. A rule blocking the operator host that listed only the LAN interface did not cut the host off under that allow rule. The same rule listing LAN and WAN did, for new connections; connections already open kept working.
- A guard rule placed ahead of such a block kept the operator's path. On the 26.1.6 scratch gateway, a floating, quick pass rule at sequence 1 for the management host's source to the gateway's LAN address on port 443, listing LAN and WAN or no interface, was followed by a floating, quick block rule at sequence 2 for the same source to any destination, listing LAN and WAN. Three new API connections after the block were answered with HTTP 200, while plain HTTP from the same host to the gateway, which answered before the block, no longer did, so the block was in force. Whether the play itself leaves the guard rule alone is a property of the play, not of the gateway.
- The savepoint cannot revert on 26.1.6. The revision it hands out has two decimals and the configuration backup it must find is named with four, so the revert call and the 60 s timer find no backup, change nothing and log `unable to revert to unexisting revision`. Neither a harmless change nor a cutting one was reverted, by the timer or by a direct revert call. Confirming a change works. The development branch has the same code. Where it works, it restores only the firewall rules, not aliases, NAT or interfaces.
- ISC DHCP is end of life upstream, and Kea is its supported replacement.
- A major release can change what the configuration relies on: an interface API appears, legacy pages move into a plugin, behaviour of the network stack changes. A release change therefore needs a test before it reaches the live gateway.

## Decision

**OPNsense remains the gateway.** The maintainer chose to stay after comparing the options below.

**The configuration describes what the lab needs.** The policy is written from the flows the other decisions require, default-deny, rather than imported from the hand-built gateway. A service the lab does not use is neither installed nor configured.

- **DHCP:** Kea only, and only on a network that has clients Tofu does not place. Tofu VMs get static addresses from cloud-init, so they have no reservations. There is no dynamic DNS.
- **DNS:** Unbound recurses directly, validates DNSSEC, and forwards each internal zone to that zone's authoritative server ([ADR 0040 (Tofu VM DNS)](../0040-dns-for-tofu-provisioned-vms/revision-000.md)). The BIND plugin is not installed.
- **GUI certificate:** the gateway holds its own certificate with its management name in the subject alternative name, and the tools verify against it. There is no ACME client and no DNS-provider token on the gateway.
- **Time:** the gateway serves NTP to the VLANs.

**Two layers define the configuration.**

| Layer | Sets | Applied by | When |
| :--- | :--- | :--- | :--- |
| Seed | Interface assignments and addresses, VLAN devices, the system settings the API cannot set (hostname, time zone, SSH, NTP, the management listen address, anti-lockout), one API user and its key | A `config.xml` on an image Tofu attaches to the VM | First boot only |
| API | Everything else: firewall policy, NAT, Unbound, Kea, packages | `oxlorg.opnsense`, run from the operator host | Every change, and every drift check |

The seed holds only what the API cannot set on the pinned release, so its interface part can be dropped once assignment is API-managed.

**Changes and drift.** The play runs with `--check --diff` before it applies. The gateway VM is snapshotted in Proxmox before each apply. The savepoint is not used, because it cannot revert on the pinned release. A floating, quick pass rule from the management hosts to the management ports comes first in the ruleset and the play never removes or reorders it, so a firewall change cannot cut the operator's path. The snapshot and the console are the way back from any other breakage. The GUI is for reading and debugging; a change made there is drift that the next check shows.

**One pin.** The OPNsense release and the collection's commit are pinned together in one place. A change to the pin is rehearsed first: a clone of the gateway on an isolated bridge is upgraded and passes smoke checks (WAN has a valid gateway, VLANs are up, a probe VM gets a lease and resolves names, NAT works, the API answers). Production is then upgraded from a Proxmox snapshot.

**Cutover.** The configuration is developed against a scratch gateway built from the seed, in the migration's isolated block. The production gateway is rebuilt from the same seed at the migration's cutover instead of being converted in place.

**Management reach.** The GUI, API and SSH accept connections only from the operator host and, until it is retired, VM 401. The subnet router is never admitted. The seed turns anti-lockout off, so the guard rule is the only way in besides the console. The Proxmox console is the way in when the network is down.

**Credentials.** The API key and secret live in the file [ADR 0048 (Tofu credentials)](../0048-where-tofu-credentials-live/revision-000.md) decides, on the host that runs the play.

**Hardening baseline,** applied by the same play: IPv6 off while unused, key-only SSH, a second factor on the GUI administrator, an API user limited to the endpoints the play calls, and direct DNS (ports 53 and 853) out of the VLANs denied except to the gateway.

## Alternatives considered

- **A plain Ubuntu gateway with nftables.** Best fit with the repo's Ansible and Molecule practice and the only option testable offline, but it has the most code to own and no GUI or plugin ecosystem.
- **VyOS.** Clean configuration model, but its LTS images need a subscription, its rolling release has no stability guarantee, and its Terraform providers are stale.
- **MikroTik CHR.** Strong Tofu provider, but closed source, and the free licence is capped at 1 Mbps.
- **pfSense CE.** Weaker automation tooling than OPNsense, and an irregular release cadence.
- **Proxmox SDN and the VM firewall.** Makes the hypervisor the router, which Tofu cannot rebuild. It stays a possible second layer.
- **The collection's savepoint revert as the safety net.** It cannot find its own backup on 26.1.6, and even where it works it restores only the firewall rules.
- **A snapshot rolled back by the play when a probe fails.** Automatic, but it needs snapshot rights for the operator host's Proxmox token and loses runtime state such as leases. The guard rule covers the operator's path without it.
- **The Tofu provider for the whole gateway.** It has no resource for assignment, system settings or packages, and its schemas change between releases.
- **A complete `config.xml` rendered and pushed.** Couples the repo to one release's XML model and offers no partial apply or rollback.
- **Importing the hand-built gateway's configuration.** Carries forward services the lab no longer uses.
- **Fronting the GUI with Caddy.** Makes the debugging path depend on a VM behind the gateway.
- **A certificate from the internal CA.** step-ca is reachable only from the proxy network and issues against a provisioner password, so it would need a new import job.
- **ACME with an external CA.** Keeps a DNS-provider token and an extra plugin on the gateway.

## Assumptions

- **Claim:** a gateway can be installed from the seeded disk without a person at the console, by a pre-installed disk image or a scripted console, at a cost the maintainer accepts.
  **Breaks if wrong:** each gateway's first install stays a manual console session, and the seed row of the table under Decision says so.
  **Checked by:** a spike of one such route on a scratch OPNsense in the isolated block: a scripted console on the serial install image, driven through the VM's serial socket so each answer waits for its prompt (`qm sendkey` has no screen to read), or a pre-installed image into which the seed is put or restored through the legacy page.
- **Claim:** Unbound forwards each internal zone to its server and keeps validating public names, without turning unsigned private zones into failures.
  **Breaks if wrong:** the private zones need to be marked insecure or served another way.
  **Checked by:** a resolution test from a probe VM against the scratch gateway.
- **Claim:** a clone of the gateway on an isolated bridge reproduces the failures a release change causes.
  **Breaks if wrong:** some failures show only on the live gateway, and snapshot rollback becomes the main safety net.
  **Checked by:** rehearsing the first release change.

## Consequences

- [ADR 0040 (Tofu VM DNS)](../0040-dns-for-tofu-provisioned-vms/revision-000.md) needs a revision: no dynamic DNS and per-zone forwards in place of delegation between the two BIND9 instances.
- [ADR 0053 (Coding-agent network reach)](../0053-network-reach-of-the-coding-agent-host/revision-000.md) names this configuration, not Tofu, as what carries its rules. The subnet router's admission there is to the coding-agent VLAN only, so this ADR's management rule does not conflict with it.
- The credentials file of ADR 0048 also feeds the Ansible play. Whether that needs a revision of ADR 0048 is decided when the play lands.
- Moving to a newer OPNsense series waits for a collection release for it.
- The settings only the seed sets are not reported by `--check --diff`. A change to one reaches an existing gateway only by hand in the GUI, and nothing detects the drift.
- The hand-built rules for the zones of ADR 0053 and ADR 0058 are written again in code on the new gateway, not imported.
- A topic doc will describe the resulting behaviour once it exists.

## Invariants

- The gateway's GUI, API and SSH accept connections only from the operator host and, until it is retired, VM 401.
- A rule admitting the management hosts to the management ports is first in the ruleset, and the play never removes or reorders it.
- The API credential is never in the repo, OpenBao or Tofu state.
- No service or plugin runs on the gateway that the configuration does not declare.
- No dynamic DNS credential exists on the gateway.

## Non-goals

- The firewall rules themselves: the flows come from the decisions that need them.
- Intrusion detection ([ADR 0039 (Intrusion detection scope)](../0039-intrusion-detection-scope/revision-000.md)).
- Where the egress proxy runs, and the tailnet policy.

## Validation

A scheduled `--check --diff` run reports drift, and the rehearsal's smoke checks gate every change to the pin.

## Reconsideration triggers

- The collection has no release for the series that OPNsense ships fixes for.
- A rehearsal fails to predict a failure on the live gateway.
- A series of OPNsense in which the savepoint revert works, which would let the play confirm its changes instead of relying on the snapshot.
