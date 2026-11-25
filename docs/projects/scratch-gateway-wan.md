---
id: PROJ-scratch-gateway-wan
title: Scratch Gateway WAN
type: project
status: building
blocked: false
summary: A zone on VLAN 10 that gives a scratch gateway on the node a route out, the gateway's resolver and a path to the node's management ports, with the scratch seed and runs changed to match.
decision: ADR-0120/0
super_project: coding-agent-host
allowed_paths:
  - ansible/roles/opnsense_gateway/**
  - ansible/tests/test_opnsense_*.py
  - tofu/modules/proxmox_opnsense_vm/seed/**
  - tofu/scratch/opnsense/**
  - tools/network_checks/**
  - tools/scratch_run/**
  - tools/tests/network_checks/**
  - tools/tests/opnsense_seed/**
  - tools/tests/scratch_run/**
  - tools/tests/shell/scratch_gateway.bats
  - docs/topics/infra/network-boundary-checks.md
  - docs/topics/infra/scratch-gateway-runs.md
  - docs/topics/infra/tofu/opnsense-gateway.md
  - docs/topics/infra/tofu/opnsense-scratch-gateway.md
  - docs/projects/coding-agent-network.md
  - docs/projects/coding-agent-egress.md
sweep_terms:
  - DEFAULT_VLANS
  - SEED_VLANS
---

# Scratch Gateway WAN

Gives a scratch gateway on the node backend a WAN again, so every run that builds a gateway there can update it, and the `coding-zone` and `dmz-probe` runs can show the node's refusals beside their controls. Staged because the zone in the play, the scratch seed and runs, and the production gateway's rebuild are separate reviewable changes.

## Scope

The zone on VLAN 10 in the gateway's play and the seed's first interface, which moves every other zone's interface one on, the scratch seed's list with its placeholder and the kit's WAN settings, the switch the scratch backends turn off, the flow list's entries for the zone, and the topic docs that describe them.

Not in: the QEMU backend's WAN, which already works; `docs/topics/infra/tofu/ubuntu-vms.md`, which names `SEED_VLANS` only to say where a VM's VLAN goes; and the rebuild of the production gateway, which is an operational run.

## Decision

Implements [ADR 0120 (Scratch gateway WAN)](../decisions/0120-where-a-scratch-gateway-on-the-node-gets-its-wan/revision-000.md), and builds only while that revision is `approved`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The seed carries VLAN 10 as its first interface, the play writes the zone with a switch both scratch backends turn off, and the scratch seed holds a placeholder in VLAN 10's position | In progress | The tests that compare the zone list with the seed pass, `--check --diff` on a scratch gateway reports no change with the zone switched off, and the zone's flows are in the flow list |
| 2 | The kit defaults the WAN to VLAN 10 | Not started | Every spec's `--check-spec` and preflight pass, and the docs describe the WAN |

The production gateway gets its VLAN 10 interface, and every other zone's interface one further on, when it is next rebuilt from the seed. The play is applied to no gateway built before that. The rebuild and the zone's first apply to it are operational runs, not stages, and the `coding-zone` run's first pass on a node-backend scratch gateway closes the project.

## Acceptance criteria

- [ ] A scratch gateway on the node leases an address, a route and the gateway's resolver from the zone, and updates.
- [ ] The `coding-zone` and `dmz-probe` runs pass their node controls.
- [ ] The zone has no flow to or from another zone, and only the scratch gateway's reserved address reaches the node, on 22 and 8006.
- [ ] A project that adds a zone carries the `flows.yaml` entries in the same change.

## Agent handoff

- **Allowed to change:** the `allowed_paths` in the frontmatter.
- **Must not change:** the production gateway by hand; the zone reaches it only through its play and its seed.
- **Relevant files and interfaces:** `tofu/modules/proxmox_opnsense_vm/seed/patch_config.py`, `ansible/roles/opnsense_gateway/`, `tofu/scratch/opnsense/`, `tools/scratch_run/`, `tools/network_checks/flows.yaml`.
- **Required checks:** `pre-commit run --all-files` and the Python unit tests.
