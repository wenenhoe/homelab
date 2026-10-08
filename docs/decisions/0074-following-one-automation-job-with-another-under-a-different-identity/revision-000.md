---
id: ADR-0074
revision: 0
type: adr
title: Following one automation job with another under a different identity
short: Job chaining
solution: A job may name successor jobs that systemd starts when it ends, each its own user and fetch, defined in the operator-applied inventory and carrying no data
summary: How the end of one CD agent job starts a second job that needs credentials the first must not hold.
topic: deployment-platform
status: approved
narrows: ADR-0044
related: [ADR-0020, ADR-0023, ADR-0072]
---

# 0074. Following one automation job with another under a different identity

## Problem

Some work is a consequence of another job's work but needs authority the first job lacks and must not gain. Rotating a leaf cloud credential is the case that exists: the rotation job holds the rotation-tier credentials and no access to managed hosts, and the deploy job reaches managed hosts and no rotation-tier credentials. Something has to run the deploy after a rotation without either identity gaining the other's authority.

## Context

[ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-c.md) starts the deploy job when `origin/main` has a commit it has not deployed, and starts every other job from its own timer. A rotation changes no commit.

A leaf rotation creates a new key, verifies it, and revokes the old one at once ([`rotation.md`](../../topics/secrets/cloud-credentials/rotation.md)). The write leaf reaches `storage` only when `deploy.yaml` next renders its `rclone.conf`, and `cloud_sync` runs there daily. Until that deploy runs, `storage` holds a key that no longer works.

Leaves rotate independently. A run can rotate and revoke some leaves and then fail on another, so a failed run leaves `storage` stale just as a successful one does, and a run that rotated nothing leaves it correct. A deploy renders from the store's current values and is idempotent, so running one when nothing changed is harmless.

systemd starts a named unit when another ends, through `OnSuccess=` and `OnFailure=` in the `[Unit]` section. Tested on systemd 255 and on 259.5, the version Ubuntu 26.04 ships on the CD agent host, with two oneshot units carrying ADR 0044's sandbox options: the second ran as a different user after the first, on success and on failure, saw none of the first's environment, and needed no timer and no enablement.

OpenBao's AppRole API generates a new secret ID on each call and lists them by accessor ([API](https://openbao.org/docs/api/auth/approle/)), so one role holds several independent secret IDs.

The write leaf's redeploy is `deploy.yaml --limit storage,localhost`, confirmed live ([`secrets-rotation.md`](../../topics/secrets/secrets-rotation.md)). The limit confines a run to `storage` and the controller; which OpenBao paths the deploy identity may read is [ADR 0020 revision 1](../0020-automation-identity-and-access-scope/revision-001.md)'s.

**Threat model.** The adversary can write to `main`, or controls a managed host or the coding-agent host, as in ADR 0044. The assets are the credentials each job holds. If what follows what were defined in the fetched tree, a merge to `main` could add a follow-on under any identity. If data passed from one job to the next, the first job could steer the second.

## Decision

- **Chaining.** A job may name successor jobs. When it ends, with any result, systemd starts each of them. A successor is a job under ADR 0044: its own unprivileged user, sandboxed unit, state directory and credentials readable only by that user, and its own fetch and clean checkout of `origin/main`. It never runs the predecessor's tree. A job has a timer, a predecessor, or both.
- **No data crosses.** The successor learns only that the predecessor ended. No output, environment, file or credential passes. It derives what it needs from OpenBao, the repository and the hosts, which is why every successor must be idempotent.
- **Defined in the inventory.** The chain's edges sit beside the jobs in the data the operator applies when provisioning the CD agent, never in anything read from a fetched commit. Provisioning rejects a cycle and a successor that names no job.
- **First use.** The rotation job's successor is `redeploy-storage`, which runs `deploy.yaml --limit storage,localhost` without `--on-change`. It has its own user, SSH key and `secret_id`, a second valid `secret_id` for the `cd-agent-deploy` AppRole, so [ADR 0020 revision 1](../0020-automation-identity-and-access-scope/revision-001.md)'s four AppRoles are unchanged.

## Alternatives considered

- **Steps within one job.** A job has one user, so a rotation-then-deploy job would hold the rotation-tier credentials and reach every managed host, which is the pairing ADR 0044 and ADR 0020 keep apart.
- **Chain definitions read from the repository, as a workflow file would be.** A merge to `main` could add a follow-on under any identity, and ADR 0044's boundary is that `main` controls what a job's code does and the operator controls which identity runs what.
- **A timer set after the rotation's.** A rotation's length varies, because verification retries through each provider's key-propagation window. An early deploy renders the old key, a late one leaves `cloud_sync` broken, and a timer cannot tell whether a rotation ran.
- **The deploy job also acting on a changed credential.** It puts OpenBao reads into the poll and decide step, which holds no credential and fetches anonymously.
- **Following only a successful run.** A failed rotation can still have revoked a key.
- **A person runs the deploy.** That is the manual step this removes.

## Consequences

- Another user, `secret_id` and SSH key to deliver and keep, for a job that runs a few minutes a month.
- A rotation run that fails before changing anything still starts a deploy, which does no harm.
- A successor's failure alerts like any job's, through the mechanism of [ADR 0072](../0072-detecting-scheduled-jobs-that-stop-running/revision-000.md). A sealed OpenBao fails both jobs.
- The role that builds the host gains chain validation, and a job that has no timer.

## Invariants

- A successor never runs its predecessor's tree, credentials, state or environment.
- No data passes between chained jobs.
- A chain is defined by data the operator applies, never by a fetched commit.
- Chains have no cycles.
- No job's user can read another job's credentials.

## Non-goals

- Steps within one job.
- Passing data between jobs.
- A job that waits for several predecessors, or follows one only after a particular result.
- Chains across hosts.
- Retrying a successor.

## Validation

- The provisioning checks that reject a cycle and an unknown successor are unit-tested.
- The role's Molecule scenario runs a chain and asserts that the successor runs as its own user after a success and after a failure, inherits no environment, and has no timer.

## Reconsideration triggers

- A second chain whose successor needs something its predecessor learned.
- A successor that must not run after a failure.
- A chain of more than two jobs.
