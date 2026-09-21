---
id: ADR-0051
revision: 0
type: adr
title: Coding-agent execution isolation
solution: A dedicated Proxmox VM without nested virtualization, running the agent unprivileged under Claude Code's built-in sandbox
summary: What isolates an autonomous coding agent's execution from the rest of the lab, given one Proxmox node shared by every VM.
topic: security-hardening
status: working
related: [ADR-0035, ADR-0043]
---

# 0051. Coding-agent execution isolation

## Problem

An autonomous coding agent runs arbitrary commands with permission prompts off. Its execution must be isolated from every other host in the lab, on a single Proxmox node that all of them share.

## Context

The node is one 6-core, 32 GB machine. [ADR 0035](../0035-container-orchestration-platform/revision-000.md) accounts for roughly 18 GB of RAM headroom, with 12 vCPU already allocated.

Claude Code's documentation names a dedicated virtual machine as the option for untrusted code. It also documents a built-in sandbox and a standalone sandbox runtime, both bubblewrap-based on Linux, which need no Docker and no hypervisor support.

Docker's `sbx` runs each agent in a microVM with a private Docker daemon. On x86_64 Linux it requires Ubuntu 24.04 or later with KVM, so inside a Proxmox guest it needs nested virtualization. It also requires a Docker account login.

**Threat model.** The adversary is a compromised agent session. The asset is everything else on the node. Network and credential separation ([ADR 0053](../0053-network-reach-of-the-coding-agent-host/revision-000.md), [ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md)) is void if the agent can escape to the hypervisor. Nested virtualization gives the guest access to KVM's nested-virtualization code on the shared node, which an ordinary guest does not exercise.

## Decision

The agent runs in a dedicated Proxmox VM with its own kernel and no nested virtualization, as an unprivileged account with Claude Code's built-in sandbox enabled. The VM sits in its own network zone ([ADR 0053](../0053-network-reach-of-the-coding-agent-host/revision-000.md)).

`sbx` and nested virtualization are not used unless [ADR 0052](../0052-molecule-runtime-without-host-privilege/revision-000.md)'s spike shows this repo's Molecule scenarios cannot run any other way; that outcome returns here as a new revision.

## Alternatives considered

- **`sbx` inside the VM.** Adds a microVM layer at the cost of nested KVM on the shared node, a Docker account login, and a sandbox lifecycle tied to that login. Held back pending the Molecule spike.
- **A container on an existing host.** Shares a kernel with production hosts. Rejected.
- **Separate hardware or a cloud VPS.** Removes the shared-hypervisor risk. Not available now; see the triggers.

## Assumptions

- **Claim:** Claude Code's built-in sandbox runs on this Ubuntu release inside the VM and does not break the repo's tooling (`uv`, `pre-commit`, `ansible-galaxy`, Molecule).
  **Breaks if wrong:** the inner layer is unusable and the VM boundary stands alone.
  **Checked by:** a throwaway spike on a scratch VM.
- **Claim:** the VM's sizing fits inside the node's remaining headroom without starving VMs 201–206 while Molecule scenarios run.
  **Breaks if wrong:** the host must shrink, or scenarios run serially, or the host moves off the node.
  **Checked by:** running the heaviest scenarios (`caddy/default`, the DinD-based ones) on a scratch VM and watching node load.

## Consequences

- A guest escape reaches the Proxmox node and everything on it. This risk is accepted while the host shares the node.
- No microVM layer inside the VM.

## Invariants

- The agent never runs as root and holds no host-level credential.
- The VM shares no kernel with any other host.

## Non-goals

- Network policy ([ADR 0053](../0053-network-reach-of-the-coding-agent-host/revision-000.md)).
- Container runtime for tests ([ADR 0052](../0052-molecule-runtime-without-host-privilege/revision-000.md)).

## Reconsideration triggers

- Spare hardware or a cloud VPS becomes available for the host.
- The Molecule spike requires `sbx`.
- Claude Code's sandbox proves unusable with the repo's tooling.
