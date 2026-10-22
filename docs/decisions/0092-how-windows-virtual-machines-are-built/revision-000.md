---
id: ADR-0092
revision: 0
type: adr
title: How Windows virtual machines are built
short: Windows VM builds
solution: Install each Windows machine from the install media with an unattended answer file that a tool in this repository renders, one VM per OpenTofu module call, with no template, no template builder and no wait for the install
summary: How the Windows desktops, and any Windows lab machine later, are created on the Proxmox node, and which tools and credentials that may use.
topic: deployment-platform
status: working
related: [ADR-0048, ADR-0090, ADR-0091]
---

# 0092. How Windows virtual machines are built

## Problem

The Windows machines are the part of the Proxmox node that nothing in the
repository can recreate. Three templates were installed by hand, and OpenTofu
stops at Ubuntu. What has to be true: a Windows machine can be rebuilt from the
repository and its install media alone, no template of unknown content sits
between them, the tools used meet
[ADR 0090 (Adopted software licences)](../0090-licences-of-adopted-software/revision-000.md),
and the credentials involved stay inside the file that
[ADR 0048 (Tofu credentials)](../0048-where-tofu-credentials-live/revision-000.md)
decides.

## Context

- **Today.** VMIDs 103, 104 and 105 are stopped, hand-built Windows templates.
  The 4XX range is marked out of scope in
  `docs/topics/infra/vm-provisioning.md`, and the node passes a GPU through to
  one desktop.
- **What the machines are.** Desktops for use and for games, rebuilt rarely.
  What matters on one is the state it accumulates, which an install does not
  produce. A lab machine that is rebuilt often is possible later.
- **Windows is not an Ubuntu cloud image.** The Ubuntu modules clone a
  template and pass the address and keys through cloud-init. Windows needs an
  agent inside the image for that, which a template builder bakes in.
- **The template builder most use fails the licence rule.** Packer's core is
  under the Business Source License from 1.10.0, which
  [ADR 0090](../0090-licences-of-adopted-software/revision-000.md) does not
  allow. Its Proxmox plugin is MPL-2.0 but runs under the core.
- **What the provider offers.** The pinned `bpg/proxmox` provider (0.117.0)
  sets a TPM state device, a 4m EFI disk with pre-enrolled keys, the `win11`
  guest type, CD-ROM images and host PCI devices, and has a resource for PCI
  hardware mappings.
- **What the token holds.** The role of the Tofu token covers VM
  configuration, CD-ROM and storage allocation on `tofu-images`, but no
  privilege to use a PCI mapping or to read the guest agent, and the Ubuntu
  module does not enable the agent.
- **Precedent for install media.** The OPNsense module downloads its ISO by URL
  and checksum, and sets the boot order to the disk first so an installed VM
  does not boot the installer again.

## Decision

- **One VM per module call, installed from the media.** A `proxmox_windows_vm`
  module takes the Windows ISO, the virtio-win ISO and an answer-file ISO, and
  creates a UEFI machine with a TPM 2.0 device, virtio disk and network, and
  the guest type for the release. Nothing is cloned.
- **The answer file is rendered by this repository.** A tool under `tools/`
  turns a template in the repo into the small ISO that carries it, so the
  install is reviewed as code. The answer file installs the virtio drivers and
  the guest agent, and holds no credential that could be reused.
- **Tofu does not wait for the install.** An apply ends when the VM is
  started, so the token needs no privilege to read the guest agent. The agent
  is enabled so a shutdown is graceful.
- **The network is the scheme's, without an address.** The NIC takes the VLAN
  and MAC the VMID fixes, and the machine takes its address from the VLAN's
  DHCP pool.
- **A GPU is passed through by a PCI mapping,** which the token may use, and
  not by a raw device.
- **A rebuild makes a fresh machine.** Its state is recovered from backups,
  which this record does not cover, and what is configured inside the guest
  after the install is not managed here.
- **No template builder for now.** One is adopted when Windows machines are
  rebuilt often enough to need clones, and it is chosen among tools that meet
  the licence rule.

## Alternatives considered

- **Packer.** Excluded by the licence rule, whatever its fit.
- **Clone the hand-built templates from Tofu.** The templates stay hand-built,
  and a clone has no way to be given a name or a network without an agent in
  the image.
- **A tool in `tools/` that drives the install through the API.** It
  reimplements waiting, key presses and cleanup that a builder provides. It
  becomes the fallback if the first assumption below fails.
- **Ansible builds the machine.** It makes Ansible a second owner of the VM's
  lifecycle, which breaks the rule that Tofu owns a VM until it can be reached.
- **Keep the templates by hand.** Nothing records what is in them.

## Assumptions

- **Claim:** the Windows setup starts from a blank disk with no key press,
  once the install media's boot image is the one that does not prompt.
  **Breaks if wrong:** the install needs a console key press that Tofu cannot
  send, and this record is revised to send it through the API from a tool, or
  to adopt a template builder.
  **Checked by:** a spike on the node that installs a Windows 11 machine from
  the three images with nothing typed on its console.
- **Claim:** the Windows ISO has no stable public address, so the operator
  uploads it once to `tofu-images` and a check compares its SHA-256 with
  Microsoft's published value before a build.
  **Breaks if wrong:** the module downloads it by URL and checksum, as the
  OPNsense module does.
  **Checked by:** reading the release's download page when the spike runs.
- **Claim:** the token can attach a PCI device through a mapping with one
  added privilege, and no raw device access.
  **Breaks if wrong:** the machine with the GPU stays outside Tofu.
  **Checked by:** a spike on the node with the GPU's mapping.
- **Claim:** the answer file can create the first account without leaving a
  reusable secret in the ISO or on the node's storage.
  **Breaks if wrong:** the ISO is a secret-bearing artifact, handled as
  [ADR 0048](../0048-where-tofu-credentials-live/revision-000.md) handles the
  token.
  **Checked by:** reading the rendered answer file and the installed account
  after the spike.

## Consequences

- A rebuild costs a full install and its updates, not a clone.
- The 4XX row of `docs/topics/infra/vm-provisioning.md` stops saying out of
  scope, and the three templates are retired or kept by a decision of the
  project that builds this.
- The token's role gains one privilege if the mapping assumption holds, which
  its table in that doc then lists.
- The Windows install media is not redistributable, so it comes from the
  operator and is never in the repository.

## Invariants

- No Windows machine depends on a template that is not built from the
  repository.
- No credential is in the repository, in the answer-file template, or in a
  rendered ISO that survives the build.
- Every tool this path uses meets the licence rule, with the Windows guest
  itself as its named exception.

## Non-goals

- Backing up or restoring a desktop's state.
- Configuration inside the guest, including GPU drivers and applications, and
  management by Ansible.
- Activation, which is [ADR 0091 (Activation host image)](../0091-where-the-activation-hosts-image-comes-from/revision-000.md)'s host.
- The node's own passthrough settings (IOMMU and the driver binding), which
  belong to the node's configuration.

## Validation

`tofu test` against the mocked provider checks the values the VMID derives and
the module's input rules, a unit test checks the rendered answer file, and a
build on the node checks the install.

## Reconsideration triggers

- Windows machines are rebuilt often enough that a clone would save real time.
- The install cannot start without a console key press.
- A Windows guest needs configuration management or an address from the repo.
