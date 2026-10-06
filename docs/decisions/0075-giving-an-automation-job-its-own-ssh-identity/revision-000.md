---
id: ADR-0075
revision: 0
type: adr
title: Giving an automation job its own SSH identity
solution: Each job that reaches hosts holds an ed25519 key generated on the CD agent and never copied off it, authorized on only the hosts it manages and only from the agent's address
summary: How a CD agent job that connects to managed hosts gets an SSH key of its own instead of the shared infrastructure key.
topic: deployment-platform
status: working
related: [ADR-0020, ADR-0044, ADR-0054, ADR-0074]
---

# 0075. Giving an automation job its own SSH identity

## Problem

A CD agent job that runs Ansible against managed hosts needs an SSH identity. Today the only one is the key every managed host trusts, which reaches all of them, and a job holding it can reach hosts its work never touches. A job's identity must reach only the hosts the job manages, and must be usable only from the agent.

## Context

`ansible/inventory/inventory.yaml` sets one `ansible_ssh_private_key_file`, `~/.ssh/proxmox_vm_servers`, under `all.vars`, and every `managed_hosts` member trusts its public half ([`network-infra.md`](../../topics/infra/network-infra.md)). [`cd-agent.md`](../../projects/cd-agent.md) records that the key is shared and unsplit. [ADR 0054](../0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md) already overrides it for one host group and gives that group's job only its own key.

Each CD agent job runs as its own user with its own credentials directory, readable only by that user ([`cd-agent-host.md`](../../topics/deploy/cd-agent-host.md)). The job's home is its state directory, and its unit's filesystem is read-only outside it.

[ADR 0074](../0074-following-one-automation-job-with-another-under-a-different-identity/revision-000.md)'s `redeploy-storage` is the first job that must reach one host and no other: it runs `deploy.yaml --limit storage,localhost`. The `deploy` job, which reaches every managed host, is the second user of the same shared key.

The host account a key opens is root-equivalent through `sudo`, as ADR 0054 accepts for its own account. A key's reach is therefore the set of hosts that authorize it.

OpenSSH's `from=` option on an `authorized_keys` entry accepts the key only from the listed source addresses.

**Threat model.** The adversary can write to `main`, or controls a job's code, as in ADR 0044. The asset is root on the hosts. The attack path is a job reading its own SSH key and using it from elsewhere, or a job reading another job's key.

## Decision

- **Generated on the agent.** The `cd_agent` role creates an ed25519 key pair for each job that declares it needs one, in that job's credentials directory, owned by the job's user and mode `0400`, only when none exists. The private half is never copied off the agent, so no operator machine or repository holds it. The role never overwrites an existing key.
- **Authorized per host group.** The public half is the only thing that leaves the agent. It is written into the data the operator applies, as public values, and the hosts the job manages authorize it for the management account with `from=` set to the agent's address. A host that is not in the job's `--limit` never authorizes it.
- **Used through the inventory.** The job's `ansible_ssh_private_key_file` is read from an environment variable the unit sets to its own key, falling back to the shared key's path where the variable is unset. The shared key stays for the operator host and for jobs that do not declare one.
- **First use.** `redeploy-storage` declares a key, and `storage` authorizes it. `deploy` keeps the shared key until a later revision moves it.

## Alternatives considered

- **Generate on the operator host and deliver the private key.** The private half would pass through a machine that holds production credentials, and through the delivery command, for no gain over generating where it is used.
- **One new key shared by every CD agent job.** Reaches every host a job in the group reaches, which is the problem for `redeploy-storage`.
- **SSH certificates from step-ca.** Short-lived and no key to authorize per host, but it needs `sshd` configuration on every host, a signing identity the agent must hold, and a CA this repository does not yet run for SSH. Not chosen yet; see the reconsideration triggers.
- **Keeping the shared key and relying on `--limit`.** The limit is a command-line argument in the job's own definition, so a job's code that opens a connection itself is not bound by it.
- **Restricting the key to a command with `command=`.** Ansible runs many commands and a module upload, so the key cannot be confined to one.

## Assumptions

- **Claim:** `storage` sees a connection from the agent as coming from `192.168.30.3`.
  **Breaks if wrong:** `from=` rejects the job's own connection, or is written with a wider range than the agent alone.
  **Checked by:** one connection from the agent to `storage`, reading `SSH_CONNECTION` on `storage`.

## Consequences

- A key to generate, fetch the public half of, and authorize for each job, once.
- Rebuilding the agent loses its keys; each job's public half must be authorized again. A key lost this way locks the job out and nothing else.
- A compromised job holds a key that reaches only its hosts, from the agent only. Root on those hosts is still reachable through it.
- Revoking a job's reach is removing one authorized entry.

## Invariants

- A job's private key exists only in its credentials directory on the agent.
- A job's key is authorized only on the hosts that job manages, and only from the agent's address.
- No job's user can read another job's key.

## Non-goals

- Moving `deploy` or the operator host off the shared key.
- Narrowing the root-equivalence of the management account.
- Rotating a job's key on a schedule.

## Validation

- The role's Molecule scenario asserts a declared key exists with its mode and owner, is not replaced by a second converge, and cannot be read by another job's user.
- A unit test over the inventory fails if a job's `--limit` names a host that does not authorize its key.

## Reconsideration triggers

- SSH certificates become available for managed hosts.
- A third job needs a key.
- A job's key has to move to a rebuilt agent without re-authorizing.
