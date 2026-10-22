---
id: ADR-0093
revision: 0
type: adr
title: How the Proxmox node is installed and configured
short: Proxmox node install
solution: Install the node from an ISO with the answer file embedded and prepared ahead, then apply its configuration with an idempotent Ansible role over SSH from any machine that holds the maintainer's key, tested on a nested Proxmox VM
summary: How the Proxmox node is reinstalled and brought to the state OpenTofu needs, given that the gateway, DNS, secrets store and controller all run on it.
topic: deployment-platform
status: working
related: [ADR-0043, ADR-0048, ADR-0092]
---

# 0093. How the Proxmox node is installed and configured

## Problem

Everything the repository provisions runs on one Proxmox node: the gateway, the
DNS and DHCP it serves, the secrets store, and the machine that runs OpenTofu
and Ansible. The node itself is installed by hand and configured from a list of
manual commands. What has to be true: a reinstalled node reaches the state
OpenTofu needs from the repository, the install media and the maintainer's
keys, and nothing it needs for that is a service that runs on the node.

## Context

- **What is configured by hand today.** `docs/topics/infra/vm-provisioning.md`
  lists it: the `tofu@pve` user, the two roles and their ACLs and the token,
  the `tofu-images` directory storage, the physical WAN bridge and the
  VLAN-aware LAN bridge, and the OPNsense VM's startup order. The settings
  that pass a GPU through are also on the node, and nothing in the repository
  records them.
- **What is down during a reinstall.** The gateway, DHCP, DNS, the secrets
  store and the controller, which is VM 401 today and the operator host that
  [ADR 0058 (Operator work host)](../0058-where-operator-work-runs/revision-000.md)
  proposes, are all virtual machines on the node.
- **The same bootstrapping order as the Tofu credentials.** Nothing needed to
  rebuild the node can be held by the secrets store that runs on it
  ([ADR 0048 (Tofu credentials)](../0048-where-tofu-credentials-live/revision-000.md)).
- **What the installer offers.** Proxmox's automated installation reads a TOML
  answer file that sets the keyboard, time zone, root password hash and SSH
  keys, the network, and the disk by filter. The file is embedded in the ISO,
  read from a partition labelled `proxmox-ais`, or fetched over HTTP at an
  address given in the ISO, by DHCP or in DNS. `proxmox-auto-install-assistant`
  prepares the ISO and checks an answer file, and reports which disks and
  network cards a filter selects. A first-boot hook, which the installer limits
  to 1 MiB, runs a script after the first boot. Keys are written in kebab
  case, and the snake case that earlier releases took is deprecated. One report
  on the 9.2-1 ISO says the DNS discovery of the answer file fails because the
  installer does not ask for the DHCP search domain.
- **The node is outside the hardening baseline.**
  [ADR 0043 (Host hardening baseline)](../0043-host-os-hardening-baseline/revision-000.md)
  excludes it.
- **No Proxmox node runs in Docker,** so a Molecule scenario cannot apply a
  role to one, and the idempotence check the repository requires of every
  scenario cannot run on it.

## Decision

- **The answer file is embedded in the ISO.** It is prepared ahead and kept
  offline, because discovery over DHCP or DNS would need the gateway that runs
  on the node being installed. A template in the repository holds everything
  except the credentials.
- **The credentials come from a file on the preparing host.** The root
  password hash and the SSH public keys are merged from a file outside the
  repository and outside the secrets store, at the time the ISO is built, as
  [ADR 0048](../0048-where-tofu-credentials-live/revision-000.md) does for
  Tofu. The ISO therefore holds a password hash and is kept as a secret.
- **Disk and network card are chosen by filter, not by name,** and checked
  against the running node with the assistant before an ISO is trusted.
- **The configuration is an Ansible role, idempotent,** applied to the node over
  SSH. It makes the node a group of its own in the inventory and carries the
  manual list above, the GPU settings and whatever the inventory of the running
  node finds. The first run after a reinstall may come from any machine that
  holds the key, so it does not wait for the controller.
- **The token's secret is read from the node and copied by hand** into the
  credentials file, as it is today.
- **It is tested on a nested Proxmox VM** on the node, with the other machines
  stopped for the test, before a real reinstall is planned.

## Alternatives considered

- **Fetch the answer file over HTTP.** It needs DHCP, DNS and a server that are
  up when the node is not, and the one report above shows the DNS path failing.
- **A second USB partition labelled for the answer file.** It keeps the ISO
  generic, at the cost of a second device to prepare and carry.
- **PXE boot.** It needs DHCP and TFTP from the same missing gateway.
- **A manual install, then the role.** It leaves the disk layout, the network
  and the root key to notes, which is the part a reinstall most needs to repeat.
- **The first-boot hook configures everything.** It puts the whole node
  configuration in a 1 MiB shell script that has no idempotent second run.

## Assumptions

- **Claim:** ADR 0056 and ADR 0058 allow the maintainer's hardware-backed key
  to be authorised for root on the node, as the one way to apply the role when
  the controller is down.
  **Breaks if wrong:** those records are revised, or the first run is made from
  the node's console.
  **Checked by:** reading both records against the use, and the maintainer's
  agreement.
- **Claim:** a nested Proxmox VM runs on this hardware, so the install and the
  role can be tried with the other machines stopped.
  **Breaks if wrong:** the first real run is the reinstall, and the
  assumptions below are checked there.
  **Checked by:** a spike that boots a nested VM and installs from an embedded
  answer file.
- **Claim:** the answer file's disk and network filters select the boot NVMe
  and the management card on the real machine.
  **Breaks if wrong:** a reinstall can wipe the wrong disk, so the filters are
  checked on the node before any ISO is used.
  **Checked by:** the assistant's device report run on the node.
- **Claim:** the node's configuration is expressible as an idempotent role with
  `pveum`, `pvesm`, file templates and handlers, without a collection for
  Proxmox.
  **Breaks if wrong:** the role needs a collection that Ansible Galaxy's
  restrictions in the sandbox make untestable, and this record names it.
  **Checked by:** a role that converges twice on a nested VM with no change.

## Consequences

- The ISO is an offline secret that holds a password hash, to be rebuilt when
  the hash or the keys change.
- The role cannot run in Molecule, so
  `docs/topics/engineering/molecule-testing.md` records it as an exception to
  the idempotence check, and a second converge with no change on a nested VM
  stands in for it.
- A reinstall still loses every machine on the node. Rebuilding them is the
  work of OpenTofu and the restore path, not of this record.
- A test needs a window in which the other machines are stopped, which includes
  the controller.

## Invariants

- No credential is in the repository or in the answer-file template.
- Nothing the install needs runs on the node being installed.
- The role reports no change when run against a node it has already
  configured.

## Non-goals

- Hardening the node, which [ADR 0043](../0043-host-os-hardening-baseline/revision-000.md)
  excludes.
- Clusters and high availability.
- Backing up or restoring the machines on the node.
- Which Proxmox repository the node updates from and how often it does.
- Anything inside a guest.

## Validation

A nested VM installs from an ISO built by the tool and converges twice with the
role, and the role run against the real node with `--check --diff` reports no
change.

## Reconsideration triggers

- A second node is added.
- ADR 0043 is revised to cover the node.
- The installer's answer file changes format, as it has before.
- A reinstall is needed while the gateway is up.
