---
id: ADR-0052
revision: 0
type: adr
title: Molecule runtime without host privilege
solution: 'Undecided: rootless Podman, rootless Docker, or a microVM-private daemon, chosen by spike'
summary: How this repo's privileged, systemd-based Molecule fixtures run on the coding-agent host without a container that has host-level root reach.
topic: security-hardening
status: working
related: [ADR-0004, ADR-0051]
---

# 0052. Molecule runtime without host privilege

## Problem

The repo's Molecule scenarios must run on the coding-agent host, and running them must not give the agent root on that host or its kernel.

## Context

Nearly every scenario uses the Docker driver against `ghcr.io/wenenhoe/molecule-dind`, with `privileged: true`, `cgroupns_mode: host`, a writable `/sys/fs/cgroup` bind, and systemd as PID 1 ([`molecule-testing.md`](../../molecule-testing.md), [`molecule-fixtures.md`](../../molecule-fixtures.md)). The exceptions are `docker` and `bind9`, which start from a different base, and lightweight scenarios such as `apt` that need neither systemd nor privileged mode.

The `secrets` role's Vault-backed scenarios start sibling containers through the Molecule control node's own Docker daemon (`molecule_helpers/tasks/start_openbao_test_target.yaml`), so they need daemon access on the host that runs Molecule.

A privileged container created by a daemon whose root is the host's root is root-equivalent on that host. [ADR 0004](../0004-container-access-to-the-docker-api/revision-000.md) already rules out handing raw daemon access to a consumer. Molecule needs a runtime where "privileged" is scoped to something the agent may already control.

Three candidates would provide that scoping:

- **Rootless Podman** through its Docker-compatible socket.
- **Rootless Docker**, where privileged is relative to a user namespace.
- **A microVM-private daemon** (`sbx`), where privileged is relative to the microVM. This requires nested virtualization and reopens [ADR 0051](../0051-coding-agent-execution-isolation/revision-000.md).

## Decision

Not yet. The candidates are compared by running the real fixtures, not by reading documentation.

## Assumptions

- **Claim:** at least one candidate runs `compose/default` (systemd plus nested Docker) to a passing `molecule test`.
  **Breaks if wrong:** the scenarios that cover the deploy path cannot run on the host, and the host either runs a reduced set or is reconsidered ([ADR 0051](../0051-coding-agent-execution-isolation/revision-000.md)).
  **Checked by:** a time-boxed spike, one candidate at a time, discarded once answered.
- **Claim:** the same candidate also runs `secrets/vault_backed`, whose sibling-container fixtures need daemon access from the Molecule control process.
  **Breaks if wrong:** the Vault-calling scenarios are excluded from the host and stay covered by CI only.
  **Checked by:** the same spike.

## Consequences

- Scenario coverage on the host may be a subset of CI's. The subset is named in [`molecule-testing.md`](../../molecule-testing.md) once known.
- GitHub-hosted CI is unchanged.

## Invariants

- The agent account never has access to a daemon socket whose root is the host's root.
- No `privileged: true` container is created by such a daemon.

## Non-goals

- Running scenarios against real hosts.
- Changing how CI runs Molecule.

## Validation

After adoption, the scenarios the host claims to run are run from `ansible/scripts/molecule-test-all.sh`, and a check confirms no host-root daemon socket is reachable from the agent account.
