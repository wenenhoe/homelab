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
- The collection can verify the gateway's TLS certificate against a CA file, but only when the name or address it connects to appears in that certificate. It can revert a firewall change that was applied under a savepoint, and it has a generic call for endpoints it has no module for. At its 26.1.11 release it has modules for VLAN devices, firewall rules and aliases, outbound NAT, Kea subnets, Unbound forwards and settings, packages and users. It has none for system settings (its `system` module only powers off, reboots, updates, upgrades and audits) or for the gateway's own certificate, which go through the generic call.
- The API credential cannot live in OpenBao for the reason [ADR 0048 (Tofu credentials)](../0048-where-tofu-credentials-live/revision-000.md) gives: OpenBao sits behind the gateway being rebuilt.
- The maintainer reaches the VLANs through the Tailscale subnet router, which source-NATs, so every tailnet node arrives at the gateway with the router's address. Only the operator host ([ADR 0058 (Operator work host)](../0058-where-operator-work-runs/revision-000.md)) and, until it is retired, VM 401 can be told apart by source address.
- OPNsense imports a configuration only on install media: its importer waits for a key press at the console, then asks which disk to read, and the installer then clones the live system's `/conf` onto the target disk. A system that boots from a disk already holding `/conf/config.xml` skips the importer. Neither prompt has an unattended mode.
- On 26.1.6 in a scratch VM, a second virtio-SCSI disk with an MBR partition table and one FAT partition holding `conf/config.xml` appears in the importer's device list as `da1`, and importing it restores the file. The installer carries it to the installed disk, which then boots without the importer prompt, with the seeded interface assignments, a root password that logs in to the GUI, and an API user whose key authenticates while a wrong secret is refused. OPNsense stores the API secret as a SHA-512 crypt hash, so the seed holds only the hash. After the import the install media's `installer` login no longer works, because the seed replaces the media's configuration. Tofu attached the seed through the gateway module, which uploaded it as import content and attached it as a second disk.
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
| Seed | Interface assignments and addresses, VLAN devices, the management listen address, one API user and its key | A `config.xml` on an image Tofu attaches to the VM | First boot only |
| API | Everything else: firewall policy, NAT, Unbound, Kea, packages, system settings | `oxlorg.opnsense`, run from the operator host | Every change, and every drift check |

The seed holds only what the API cannot set on the pinned release, so its interface part can be dropped once assignment is API-managed.

**Changes and drift.** The play runs with `--check --diff` before it applies. A firewall change is applied under a savepoint and confirmed, so a change that cuts the management path reverts itself. The GUI is for reading and debugging; a change made there is drift that the next check shows.

**One pin.** The OPNsense release and the collection version are pinned together in one place. A change to the pin is rehearsed first: a clone of the gateway on an isolated bridge is upgraded and passes smoke checks (WAN has a valid gateway, VLANs are up, a probe VM gets a lease and resolves names, NAT works, the API answers). Production is then upgraded from a Proxmox snapshot.

**Cutover.** The configuration is developed against a scratch gateway built from the seed, in the migration's isolated block. The production gateway is rebuilt from the same seed at the migration's cutover instead of being converted in place.

**Management reach.** The GUI, API and SSH accept connections only from the operator host and, until it is retired, VM 401. The subnet router is never admitted. The Proxmox console is the way in when the network is down.

**Credentials.** The API key and secret live in the file [ADR 0048 (Tofu credentials)](../0048-where-tofu-credentials-live/revision-000.md) decides, on the host that runs the play.

**Hardening baseline,** applied by the same play: IPv6 off while unused, key-only SSH, a second factor on the GUI administrator, an API user limited to the endpoints the play calls, and direct DNS (ports 53 and 853) out of the VLANs denied except to the gateway.

## Alternatives considered

- **A plain Ubuntu gateway with nftables.** Best fit with the repo's Ansible and Molecule practice and the only option testable offline, but it has the most code to own and no GUI or plugin ecosystem.
- **VyOS.** Clean configuration model, but its LTS images need a subscription, its rolling release has no stability guarantee, and its Terraform providers are stale.
- **MikroTik CHR.** Strong Tofu provider, but closed source, and the free licence is capped at 1 Mbps.
- **pfSense CE.** Weaker automation tooling than OPNsense, and an irregular release cadence.
- **Proxmox SDN and the VM firewall.** Makes the hypervisor the router, which Tofu cannot rebuild. It stays a possible second layer.
- **The Tofu provider for the whole gateway.** It has no resource for assignment, system settings or packages, and its schemas change between releases.
- **A complete `config.xml` rendered and pushed.** Couples the repo to one release's XML model and offers no partial apply or rollback.
- **Importing the hand-built gateway's configuration.** Carries forward services the lab no longer uses.
- **Fronting the GUI with Caddy.** Makes the debugging path depend on a VM behind the gateway.
- **A certificate from the internal CA.** step-ca is reachable only from the proxy network and issues against a provisioner password, so it would need a new import job.
- **ACME with an external CA.** Keeps a DNS-provider token and an extra plugin on the gateway.

## Assumptions

- **Claim:** a gateway can be installed from the seeded disk without a person at the console, by a pre-installed disk image or a scripted console, at a cost the maintainer accepts.
  **Breaks if wrong:** each gateway's first install stays a manual console session, and the seed row of the table under Decision says so.
  **Checked by:** a spike of one such route on a scratch OPNsense in the isolated block.
- **Claim:** at the pinned release the modules, and a generic-call recipe for system settings and the certificate, cover every object the policy needs, and `--check --diff` reports drift accurately, including for objects set through the generic call and for Unbound forwards.
  **Breaks if wrong:** the missing objects need a small module of ours or an upstream contribution, which adds code to maintain.
  **Checked by:** the same spike, running the play twice and with a deliberate manual change.
- **Claim:** a firewall change applied under a savepoint reverts by itself when the management path is cut.
  **Breaks if wrong:** changes that can cut the path need a second, out-of-band revert.
  **Checked by:** the spike, by applying a rule that blocks the management source.
- **Claim:** the gateway can hold a certificate that carries its management name in the subject alternative name, created without its private key entering the repo or the Tofu state, and the collection verifies it from a CA file.
  **Breaks if wrong:** the play connects with verification off, or the certificate comes from another source.
  **Checked by:** the spike, creating and activating the certificate through the API and connecting with verification on.
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
- The hand-built rules for the zones of ADR 0053 and ADR 0058 are written again in code on the new gateway, not imported.
- A topic doc will describe the resulting behaviour once it exists.

## Invariants

- The gateway's GUI, API and SSH accept connections only from the operator host and, until it is retired, VM 401.
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
