---
id: PROJ-cd-agent-credential-delivery
title: CD Agent Credential Delivery
type: project
status: not-started
blocked: false
summary: One operator-host command that delivers each CD agent job's credentials, and the secret_id rotation that reuses it.
decision: ADR-0047/0
super_project: pull-based-cd
track: credentials
depends_on:
  - project: PROJ-cd-agent-approles
    reason: the roles, policies and file names it delivers must exist first
---

# CD Agent Credential Delivery

[`cd-agent-approles.md`](cd-agent-approles.md) defines what each job reads from its
credentials directory and documents the handoff as a runbook. This project
turns that runbook into one command, and rotates each `secret_id` with it.

## Scope

A command run from the operator host that delivers one job's credential
files to `cd_agent`, and the rotation of a job's `secret_id` using the same
command. Not in scope: the roles and their policies
([`cd-agent-approles.md`](cd-agent-approles.md)), the host and its jobs
([`cd-agent.md`](cd-agent.md)), and retiring `controller`'s AppRole
([`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)).

## Decision

Implements the `secret_id` handoff of
[ADR 0047 (First-credential bootstrap)](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md),
`approved`: a response-wrapped value requested through `vault-bootstrap`,
carried on SSH stdin and unwrapped once on `cd_agent`. The wrapping call
needs the `vault-bootstrap` AppRole's `secret_id`, typed at a hidden prompt,
so the command is run by a person and is not unattended. How
[ADR 0020 revision 1 (Automation identity scope)](../decisions/0020-automation-identity-and-access-scope/revision-001.md)
leaves the rotation cadence to a project is settled in Stage 2.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Deliver a job's credentials | Not started | one command writes a job's `openbao-controller-secret-id`, `openbao-controller-role-id`, `main-domain` and `step-ca-root.crt` into its credentials directory with the owner and modes the job expects, and the job logs in |
| 2 | Rotate a `secret_id` | Not started | the same command adds a new `secret_id`, a login with it is confirmed, and the old one is destroyed by its accessor, with no failed job run in between |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — Delivery

For one job: request a wrapped `secret_id` for its AppRole, send the
wrapping token to `cd_agent` over SSH stdin, unwrap it there into the job's
`0400` file, and write the other three files, which are not secret, beside
it. A job's second `secret_id`, such as `cd-agent-deploy`'s for
`redeploy-storage` ([ADR 0074 (Job chaining)](../decisions/0074-following-one-automation-job-with-another-under-a-different-identity/revision-000.md)),
is the same command for another job's directory. The files and their names
are in
[`openbao-cd-agent-approles.md`](../topics/secrets/openbao-cd-agent-approles.md).

### Stage 2 — Rotation

An AppRole holds several `secret_id`s at once, so a rotation adds the new one,
confirms a login with it, then destroys the old one by its accessor.
Rotate when `cd_agent` is rebuilt or re-provisioned, when the operator host's
credentials change, on any suspected exposure, and every 90 days. The
`secret_id` has no expiry of its own, so a missed rotation is not an outage.

## Acceptance criteria

- [ ] One command delivers a job's four files, each with the owner and mode the job needs, and a job started afterwards logs in to OpenBao, verified.
- [ ] The wrapping token never appears in a process argument or a log, and a second unwrap of it fails, verified.
- [ ] A rotation leaves exactly one valid `secret_id` for that job and no failed run, verified.
- [ ] A step-ca root change is covered by re-running delivery for every job, and the deploy-side check then passes, verified.
- [ ] The rotation cadence and its triggers are in a topic doc.

## Risks

- A wrapping token has a short lifetime, so a delivery that stalls between the wrap and the unwrap has to be repeated.
- A wrong file name or mode breaks a job on its next run, so the command verifies each file before it reports success.

## Open items

- What reminds the maintainer that a 90-day rotation is due is not decided. The freshness job cannot read the `secret_id`'s age, since its policy grants no `auth/approle` capability.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or named by a successor project.
- [ ] The linked revision is `accepted`, another project still names it, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
- [ ] No code comment, message or topic doc still names this project's stages, phases or tracks.
