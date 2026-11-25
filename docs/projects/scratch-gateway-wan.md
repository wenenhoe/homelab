---
id: PROJ-scratch-gateway-wan
title: Scratch Gateway WAN
type: project
status: not-started
blocked: false
summary: A zone on VLAN 10 that gives a scratch gateway on the node a route out, the gateway's resolver and a path to the node's management ports, with the scratch seed and runs changed to match.
decision: ADR-0120/0
super_project: coding-agent-host
---

# Scratch Gateway WAN

Gives a scratch gateway on the node backend a WAN again, so every run that builds a gateway there can update it, and the `coding-zone` and `dmz-probe` runs can show the node's refusals beside their controls. Staged because the zone in the play, the scratch seed and runs, and the production gateway's rebuild are separate reviewable changes.

## Scope

The zone on VLAN 10 in the gateway's play and the seed's ninth interface, the scratch seed's list and the kit's WAN settings, the runs' play variables, the flow list's entries for the zone, and the topic docs that describe them. Not in scope: the QEMU backend, and the rebuild of the production gateway, which is an operational run.

## Decision

Implements [ADR 0120 (Scratch gateway WAN)](../decisions/0120-where-a-scratch-gateway-on-the-node-gets-its-wan/revision-000.md), and builds only while that revision is `approved`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The seed carries VLAN 10 as its ninth interface, the play writes the zone with a switch the scratch runs turn off, and the scratch seed leaves VLAN 10 out | Not started | The tests that compare the zone list with the seed pass, `--check --diff` on a scratch gateway reports no change with the zone switched off, and the zone's flows are in the flow list |
| 2 | The kit defaults the WAN to VLAN 10 and the run specs play the zone switched off | Not started | Every spec's `--check-spec` and preflight pass, and the docs describe the WAN |

The production gateway gets its VLAN 10 interface when it is next rebuilt from the seed. The rebuild and the zone's first apply to it are operational runs, not stages, and the `coding-zone` run's first pass on a node-backend scratch gateway closes the project.

## Acceptance criteria

- [ ] A scratch gateway on the node leases an address, a route and the gateway's resolver from the zone, and updates.
- [ ] The `coding-zone` and `dmz-probe` runs pass their node controls.
- [ ] The zone has no flow to or from another zone, and only the scratch gateway's reserved address reaches the node, on 22 and 8006.
- [ ] A project that adds a zone carries the `flows.yaml` entries in the same change.

## Agent handoff

- **Allowed to change:** to be set with `allowed_paths` before the project is `building`.
- **Must not change:** the production gateway by hand; the zone reaches it only through its play and its seed.
- **Relevant files and interfaces:** `tofu/modules/proxmox_opnsense_vm/seed/patch_config.py`, `ansible/roles/opnsense_gateway/`, `tofu/scratch/opnsense/`, `tools/scratch_run/`, `tools/network_checks/flows.yaml`.
- **Required checks:** `pre-commit run --all-files` and the Python unit tests.

## Open items

- How the runs switch the zone off, as a play variable the backends set or in each spec.
