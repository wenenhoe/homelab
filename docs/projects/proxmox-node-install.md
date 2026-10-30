---
id: PROJ-proxmox-node-install
title: Proxmox Node Install
type: project
status: not-started
blocked: false
summary: The Proxmox node reinstalled from an ISO with an embedded answer file and brought to the state OpenTofu needs by an idempotent Ansible role, tested on a nested Proxmox VM.
decision: ADR-0093/0
super_project: tofu-vm-provisioning
track: proxmox
allowed_paths:
  - tools/proxmox_install/**
  - tools/tests/proxmox_install/**
  - ansible/roles/proxmox_node/**
  - ansible/playbooks/proxmox_node.yaml
  - ansible/inventory/inventory.yaml
  - docs/topics/infra/proxmox-node.md
  - docs/topics/infra/vm-provisioning.md
  - docs/topics/engineering/molecule-testing.md
  - docs/topics/README.md
---

# Proxmox Node Install

Makes the Proxmox node reproducible: an install ISO that carries its own answer file, and an Ansible role that brings a freshly installed node to the state OpenTofu needs, as [ADR 0093 (Proxmox node install)](../decisions/0093-how-the-proxmox-node-is-installed-and-configured/revision-000.md) decides. It is staged because the first stages find out what the running node holds and whether a nested node can stand in for it, and the later ones build on both.

## Scope

An inventory of the running node's settings, written up in the new topic doc `docs/topics/infra/proxmox-node.md`. The answer-file template and the tool in `tools/proxmox_install/` that merges the credentials and builds the ISO, with its tests. The role `ansible/roles/proxmox_node/`, its playbook `ansible/playbooks/proxmox_node.yaml` and the node's group in `ansible/inventory/inventory.yaml`. The manual steps in `docs/topics/infra/vm-provisioning.md` become pointers to the role, and the role's exception to the idempotence check is recorded in `docs/topics/engineering/molecule-testing.md`. The new topic doc needs its row in `docs/topics/README.md`.

Not in this project: hardening the node, clusters, backups and restores of the machines on it, Proxmox's update repositories, and the real reinstall, which is a planned outage the maintainer chooses. The Tofu modules and their tests keep taking the `tofu-images` storage and the bridge names as inputs, since the role creates what they name.

## Decision

Implements [ADR 0093 (Proxmox node install)](../decisions/0093-how-the-proxmox-node-is-installed-and-configured/revision-000.md), still `working`. The project stays `not-started` until that revision is `approved`. Stage 1 is a spike and the only work that may start before then.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike: boot a nested Proxmox VM on the node with the other machines stopped, install it from an ISO with an embedded answer file, and run the assistant's device report on the real node | Not started | Each of the ADR's four assumptions is recorded as held or as broken, with what the spike showed |
| 2 | Inventory the running node's settings and write them up | Not started | The topic doc lists every node-level setting the machines depend on, including the GPU passthrough settings, each with how it is set |
| 3 | The answer-file template and the ISO tool | Not started | The tool merges the credentials from a file outside the repository, `validate-answer` accepts what it renders, and its tests check that no credential reaches the template or the repository |
| 4 | The role and playbook, converged on a nested VM | Not started | The role converges on a freshly installed nested VM, and a second run reports no change |
| 5 | Reconcile the role with the running node | Not started | `--check --diff` against the real node reports no change, and the manual steps in the VM provisioning doc point at the role |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] An ISO built by the tool installs a nested Proxmox VM unattended, and no credential is in the repository or the template.
- [ ] The role converges on that VM and reports no change on a second run.
- [ ] `--check --diff` of the role against the real node reports no change.
- [ ] The topic doc lists the node's settings, and the VM provisioning doc points at the role for the steps it listed.
- [ ] The role's exception to the idempotence check is recorded with the check that stands in for it.
- [ ] The ADR is `accepted`.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the ADR's Decision, the node, its disks and its credentials, and any ISO. The maintainer runs the installer and the nested test.
- **Relevant files and interfaces:** `docs/topics/infra/vm-provisioning.md` for the manual steps and the token's privileges, and the existing roles for the Ansible conventions.
- **Required checks:** `pre-commit run --all-files`, `uv run pytest` from `tools/`, and `ansible-lint` run by hand.

## Risks

- A test needs the other machines stopped, which includes the controller and the gateway, so it is an outage.
- A filter that selects the wrong disk would wipe it on a real reinstall, so Stage 1's device report is checked before any ISO is used.
- The role cannot run in Molecule, so its only idempotence evidence is a run on a nested VM.
- The installer's answer-file format has changed between releases.

## Open items

- Whether the first run after a reinstall may use the maintainer's hardware-backed key, which the ADR's first assumption leaves to the maintainer and ADRs 0056 and 0058.
- When the node reinstall is scheduled relative to the cutover in [`tofu-migration.md`](tofu-migration.md), since both need an outage.
- The node is a member of the tailnet, joined by hand, and is the maintainer's way to the hypervisor when the router VM is broken. A reinstall removes that join. Stage 2 records how the node joined, and the role or the reinstall has to restore the membership under the tag and with the one-time key handling that [ADR 0097 (Tailscale node configuration)](../decisions/0097-how-a-tailscale-node-is-configured/revision-000.md) sets, which may mean applying that ADR's role to the node.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
