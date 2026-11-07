---
id: EXP-molecule-runtime-without-host-privilege
title: "Which container runtime can run the Molecule scenarios on the coding-agent host without giving the agent root there?"
type: exploration
status: open
summary: "How this repo's privileged, systemd-based Molecule fixtures run on the coding-agent host without a container that has host-level root reach."
topic: security-hardening
related: [ADR-0004, ADR-0051]
---

# Which container runtime can run the Molecule scenarios on the coding-agent host without giving the agent root there?

The repo's Molecule scenarios must run on the coding-agent host, and running them
must not give the agent root on that host or its kernel. Which runtime does that
is answered by running the real fixtures, not by reading documentation.

## What bears on it

- Nearly every scenario uses the Docker driver against the `molecule-dind`
  image, with `privileged: true`, `cgroupns_mode: host`, a writable
  `/sys/fs/cgroup` bind and systemd as PID 1
  ([`molecule-testing.md`](../topics/engineering/molecule-testing.md),
  [`molecule-fixtures.md`](../topics/engineering/molecule-fixtures.md)). The
  exceptions are `docker` and `bind9`, which start from a different base, and
  lightweight scenarios such as `apt` that need neither systemd nor privileged
  mode.
- The `secrets` role's Vault-backed scenarios start sibling containers through
  the control node's own Docker daemon
  (`molecule_helpers/tasks/start_openbao_test_target.yaml`), so they need daemon
  access on the host that runs Molecule.
- A privileged container created by a daemon whose root is the host's root is
  root-equivalent on that host.
  [ADR 0004](../decisions/0004-container-access-to-the-docker-api/revision-000.md)
  already rules out handing raw daemon access to a consumer. Molecule needs a
  runtime where "privileged" is scoped to something the agent may already
  control.
- Constraints any answer must keep: the agent account never has access to a
  daemon socket whose root is the host's root, and no `privileged: true`
  container is created by such a daemon. Not in question: running scenarios
  against real hosts, and how CI runs Molecule.
- What follows from the answer: scenario coverage on the host may be a subset of
  CI's, and that subset is named in `molecule-testing.md` once known.

## Options

1. **Rootless Podman** through its Docker-compatible socket.
2. **Rootless Docker**, where privileged is relative to a user namespace.
3. **A microVM-private daemon** (`sbx`), where privileged is relative to the
   microVM. It needs nested virtualization and reopens
   [ADR 0051](../decisions/0051-coding-agent-execution-isolation/revision-000.md).

## What has to be checked first

- At least one option runs `compose/default` (systemd plus nested Docker) to a
  passing `molecule test`. If none does, the scenarios that cover the deploy path
  cannot run on the host, and the host either runs a reduced set or is
  reconsidered. Checked by a time-boxed spike, one option at a time, discarded
  once answered.
- The same option also runs `secrets/vault_backed`. If not, the Vault-calling
  scenarios are excluded from the host and stay covered by CI only.

## Leaning

None. After adoption the claimed scenarios are run from
`ansible/scripts/molecule-test-all.sh`, and a check confirms no host-root daemon
socket is reachable from the agent account.
