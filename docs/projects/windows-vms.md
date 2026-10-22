---
id: PROJ-windows-vms
title: Windows VMs
type: project
status: not-started
blocked: false
summary: Windows machines created by OpenTofu from their install media with an unattended answer file rendered in this repository, starting with the desktops and the one with a GPU.
decision: ADR-0092/0
super_project: tofu-vm-provisioning
track: windows
allowed_paths:
  - tofu/modules/proxmox_windows_vm/**
  - tofu/main.tf
  - tofu/variables.tf
  - tofu/outputs.tf
  - tofu/tests/proxmox_windows_vm.tftest.hcl
  - tofu/tests/root.tftest.hcl
  - tools/windows_unattend/**
  - tools/tests/windows_unattend/**
  - docs/topics/infra/vm-provisioning.md
---

# Windows VMs

Brings the Windows machines under OpenTofu, which today stops at Ubuntu and OPNsense, as [ADR 0092 (Windows VM builds)](../decisions/0092-how-windows-virtual-machines-are-built/revision-000.md) decides. A machine is installed from its media with an answer file this repository renders, so nothing depends on a hand-built template. It is staged because the first stage is a spike on the node whose answers decide the module's shape.

## Scope

The answer-file renderer in `tools/windows_unattend/`, the `proxmox_windows_vm` module in `tofu/modules/proxmox_windows_vm/`, its tests, the root module's call for the first desktop and the input variables it needs, and the 4XX row, the Windows section and the token table of `docs/topics/infra/vm-provisioning.md`. Then the desktop with a GPU, which needs a PCI mapping and one more privilege for the token.

Not in this project: backing up a desktop's state, configuration inside the guest, management by Ansible, the node's own IOMMU and driver settings, the activation host, and VM 401, which runs the repository's tooling and stays outside Tofu. The three templates' fate is the last stage's decision. Other files that match a search for Windows, for the VMID 103 or for "out of scope" do so in unrelated words, version numbers or fixtures.

## Decision

Implements [ADR 0092 (Windows VM builds)](../decisions/0092-how-windows-virtual-machines-are-built/revision-000.md), still `working`. The project stays `not-started` until that revision is `approved`. Stage 1 is the spike that resolves its four assumptions, and it is the only work that may start before then.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike on the node: install a Windows 11 machine from blank disk with the three images and nothing typed on its console, and try a PCI mapping for the GPU | Not started | Each of the ADR's four assumptions is recorded as held or as broken, with what the spike showed |
| 2 | The answer-file renderer and its tests | Not started | A template in the repository renders to a small ISO that carries the answer file, a unit test checks the rendered file, and nothing in it is a credential |
| 3 | The `proxmox_windows_vm` module, its tests and the first desktop | Not started | `tofu test` passes against the mocked provider, `tofu plan` shows the machine, applying it installs Windows unattended on the node, and the topic doc describes the module and the 4XX range |
| 4 | The desktop with the GPU, by a PCI mapping | Not started | The token holds the one added privilege, listed in its table, and the machine starts with the GPU attached |
| 5 | Decide the fate of the templates 103, 104 and 105 | Not started | Each is retired or kept with a recorded reason, and the topic doc no longer lists a Windows machine as built by hand |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] A Windows 11 desktop is created by `tofu apply` from the install media and the rendered answer file, with no template and nothing typed on its console.
- [ ] No credential is in the repository, the answer-file template or a rendered ISO that survives the build.
- [ ] The machine's VLAN and MAC come from its VMID, and it takes its address from the VLAN's DHCP pool.
- [ ] The desktop with the GPU is created with the GPU attached through a PCI mapping, and the token's added privilege is listed.
- [ ] `docs/topics/infra/vm-provisioning.md` describes the module and no longer marks the 4XX range out of scope.
- [ ] Each of the templates 103, 104 and 105 is retired or kept with a recorded reason.
- [ ] The ADR is `accepted`.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the ADR's Decision, the Windows install media, and the Proxmox node's configuration or token, which the maintainer changes by hand.
- **Relevant files and interfaces:** the OPNsense and Ubuntu modules in `tofu/modules/` for the module shape, and `tofu/tests/` for how the provider is mocked.
- **Required checks:** `tofu fmt -check -recursive`, `tofu validate` and `tofu test` from `tofu/`, and `uv run pytest` from `tools/`.

## Risks

- The install may need a console key press that Tofu cannot send. The ADR names the fallback.
- The remastered install image is several gigabytes and has to be stored on the node's image storage.
- A rebuilt desktop loses its state, so a rebuild waits for a backup.
- Windows 11 requirements change between releases, so the module's hardware may need an update.

## Open items

- Which of the templates 103, 104 and 105 are still wanted, which Stage 5 decides.
- Whether a Windows lab machine appears that is rebuilt often, which would reopen the template builder question in the ADR.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
