---
id: PROJ-tofu-migration
title: Tofu Migration
type: project
status: building
blocked: false
summary: Move Tofu's state off the dev VM into a remote backend, so Tofu's record of what it built no longer depends on one VM.
super_project: tofu-vm-provisioning
track: migration
---

# Tofu Migration

The Ubuntu VMs are built by Tofu on their real VMID ranges, the old VMs are decommissioned and the generated inventory replaces the hand-written entries. What is left is Tofu's state, which is still a local file on the dev VM. It moves into an S3-compatible remote backend.

The procedures the rebuilds used are now topic docs: [`rebuild-runbook.md`](../topics/disaster-recovery/rebuild-runbook.md) for the cycle, [`rebuild-storage.md`](../topics/disaster-recovery/rebuild-storage.md) for `storage`, and [`rebuild-tools.md`](../topics/disaster-recovery/rebuild-tools.md) for the scripts and the dump storage. The design they build on is [`vm-provisioning.md`](../topics/infra/vm-provisioning.md). The gateway (VM 201) is rebuilt by [`opnsense-config.md`](opnsense-config.md), not here.

## Scope

Moving Tofu's state from the dev VM to a remote backend, and the copies the rebuilds took. VMIDs 103–105 and 401–403 are not in any Ansible inventory and are out of scope, as is the production gateway's rebuild and its day-2 configuration.

## Decision

No ADR for the first two stages; the design is [`vm-provisioning.md`](../topics/infra/vm-provisioning.md), a topic doc that predates ADRs.

Stage 3 carries out [ADR 0103 (Tofu state backend)](../decisions/0103-where-tofus-state-is-held/revision-000.md), which is `working`. Stage 3 does not start until that revision is `approved` and this doc names it in `decision:`.

## Execution plan

Update at the start and end of each PR that works a stage. Stage status is `Not started`, `In progress`, or `Done`.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Build the 5XX block, first `restore.yaml` run | Done | the 5XX block is built by Tofu, isolated from production, and the first `restore.yaml` run against it succeeds |
| 2 | Cutover to real VMID ranges, decommission old VMs | Done | the Ubuntu VMs are rebuilt on the real VMID ranges, traffic is cut over, the generated inventory replaces the hand-written entries, and the old Ubuntu VMs are decommissioned with `storage` up throughout |
| 3 | Move Tofu's state to a remote backend | Not started | the backend is decided by [ADR 0103](../decisions/0103-where-tofus-state-is-held/revision-000.md), `tofu init -migrate-state` has moved the state into it, the dev VM's file is no longer the only copy, and [`vm-provisioning.md`](../topics/infra/vm-provisioning.md#state-backend--secrets) describes the backend |

### Stage 3 — remote state

Tofu's state is a local file on the dev VM, and each rebuild changed it. The state moves into the S3-compatible backend that [`vm-provisioning.md`](../topics/infra/vm-provisioning.md#state-backend--secrets) plans, so it no longer depends on one VM.

| Part | State |
| :--- | :--- |
| Backend | An encrypted `opentofu-state` bucket on R2 and B2: one provider live, the other holding a GPG copy pushed after each apply ([ADR 0103](../decisions/0103-where-tofus-state-is-held/revision-000.md)) |
| Which provider is live, and the lock | Open: a bucket check on each provider settles it before the ADR can be `approved` |
| Credentials | A state credential and an encryption key, in the credentials file ([ADR 0048](../decisions/0048-where-tofu-credentials-live/revision-000.md)) |
| Move | `tofu init -migrate-state` from the operator host |
| Cleanup | Delete the local copies the rebuilds took once a plan against the bucket shows no change |

## Acceptance criteria

- [x] The 5XX block (OPNsense plus one Ubuntu VM on VLAN 50) is built by Tofu and isolated from production.
- [x] The first `restore.yaml` run against it succeeds, as the restore-path fire drill.
- [x] Every Ubuntu VM is rebuilt on the real VMID ranges by Tofu.
- [x] The generated inventory replaces the hand-written entries, including `tailscale`.
- [x] The old Ubuntu VMs are decommissioned.
- [x] The rebuilt `tailscale` VM carries its tag, has its route approved without the console and has no key expiry.
- [x] `storage` stayed up throughout.
- [x] Every rebuilt host was backed up on demand before its old VM was dumped, and the OpenBao snapshot was taken and restored on the rebuilt `security`.
- [x] Every rebuilt host's restores are in the fire drill's results.
- [x] A copy of Tofu's state was taken after each rebuild's apply.
- [ ] Tofu's state is held by a remote backend, and a plan against it shows no change.
- [x] The resulting behavior is described in topic docs, not only here.

## Risks

Could cause rework or delay but blocks nothing now — no live vulnerability, incident, or exposure window ([`docs/README.md#public-repo`](../README.md#public-repo)).

- Until Stage 3, every copy of Tofu's state is on the dev VM, so losing that VM loses the record of what Tofu built. Retiring the dev VM ([`workstation-management.md`](workstation-management.md)) must wait for Stage 3.

## Open items

- Which of R2 and B2 is the live backend, and whether either honours conditional writes for the lock. [ADR 0103](../decisions/0103-where-tofus-state-is-held/revision-000.md) leaves both to a bucket check before it can be `approved`.
- Whether `tailscale` needs the 2 vCPU and 2 GB its module call gives it. The VM is a routing appliance that runs `tailscaled` and the guest agent and no Docker, so it may need less than the hosts the keep-current-size rule was written for. At idle the guest used about 200 MB of its 2 GiB and `tailscaled` about 50 MB, but an idle reading says nothing about the load to come: once the operator host and the laptop replace VM 401, every operator session crosses the router ([ADR 0097](../decisions/0097-how-a-tailscale-node-is-configured/revision-000.md)). Measure its memory, CPU and throughput on the live VM under that traffic, over runs that span real operator sessions, and resize it in its module call if the numbers allow.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
