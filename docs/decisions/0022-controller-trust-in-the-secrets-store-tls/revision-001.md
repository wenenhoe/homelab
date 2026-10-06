---
id: ADR-0022
revision: 1
type: adr
title: Controller trust in the secrets store's TLS certificate
solution: The step-ca root fetched fresh where a host can reach security, and a delivered copy, checked against the live root, where it cannot
summary: How the controller verifies OpenBao's TLS certificate without skip-verify or a committed copy of the CA.
topic: secrets-store
status: approved
supersedes: 0
related: [ADR-0020, ADR-0044, ADR-0047]
---

# 0022. Controller trusts OpenBao's TLS cert via the step-ca root: fetched fresh where possible, delivered where not

## Context

[Revision 0](revision-000.md) has every run read step-ca's `root_ca.crt` over
SSH from `security` into a per-run temp file, so no CA copy is committed and
nothing skips verification. That needs an SSH key to `security`.

[ADR 0044](../0044-prod-automation-trigger-and-execution/revision-000-c.md) runs
the freshness and rotation jobs on `cd_agent` as their own users, each holding
only its own AppRole credential
([ADR 0020 revision 1](../0020-automation-identity-and-access-scope/revision-001.md)).
Giving each of them a key to `security` would widen what a compromised job
reaches on the host that holds the secrets store and the CA, which is the
boundary this design keeps narrow. Without the root cert, though, a job cannot
verify OpenBao and cannot log in.

step-ca's root is public. What a job needs is the right copy of it, not a
secret.

## Decision

Where a host can reach `security` over SSH, nothing changes from revision 0:
the root is fetched fresh each run into a randomly named temp file and used
for every call to OpenBao that run.

A job that holds no such key gets a copy of the root in its credentials
directory, as `step-ca-root.crt` beside the AppRole files, delivered with them
([ADR 0047](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md)).
The tooling uses that file when it exists in the file cache and fetches
otherwise, so an operator's checkout, which never has one, behaves as before.
A delivered file that is not a PEM certificate stops the run with a message
naming it. The tooling never falls back to skipping verification.

Wherever a run has both the delivered copy and a fresh fetch, it requires them
to be equal and fails naming the delivered file when they are not. The run
keeps using the fetched root. A delivered copy that no run can compare, because
that run cannot reach `security`, is found stale only by failing TLS
verification.

A change of step-ca's root is handled by redelivering the new root to every
job's credentials directory, then running a job that can compare.

## Alternatives considered

- **An SSH key to `security` for each job.** Keeps revision 0's mechanism and
  nothing else changes, but every job gains a path onto the host that holds
  the secrets store and the CA, for a value that is public.
- **Fetch `/roots.pem` over HTTPS and check it against a pinned
  fingerprint.** Stateless to run, but the pin goes stale exactly when a
  delivered copy would, and the fetch itself is unauthenticated until the pin
  is checked.
- **Commit the root to the repository.** Revision 0 rejected this because
  nothing re-checks the copy against the live CA. The check above would, but
  doing so moves the trust anchor into the repository for a value the CA owns,
  and gains nothing a delivered file does not already give.

## Consequences

- A step-ca root change breaks every job's TLS verification until its file is
  redelivered. The failure is loud and never a quiet fallback. The root changes
  only when it is regenerated or expires.
- The comparison covers only a copy that a run which can reach `security` also
  holds. The other jobs' copies are not compared against anything.
- The delivered file is public. It needs no wrapped handoff, only the same
  owner as the credential files beside it.
- Revision 0's per-run fetch, its temp-file handling and its requirement that
  a run reaching `security` use an explicit SSH connection all stand.

Behavior is described in
[`openbao-cd-agent-approles.md`](../../topics/secrets/openbao-cd-agent-approles.md)
and [`secrets.md`](../../topics/secrets/secrets.md).

## Invariants

- No run skips TLS verification of OpenBao.
