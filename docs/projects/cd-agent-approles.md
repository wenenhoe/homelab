---
id: PROJ-cd-agent-approles
title: CD Agent Credentials
type: project
status: building
blocked: false
summary: The CD agent's four CIDR-bound AppRoles, and the delivery and rotation of each job's credentials.
decision: ADR-0020/1
also_implements: [ADR-0022/1]
super_project: pull-based-cd
track: credentials
---

# CD Agent Credentials

Second of three projects in the `pull-based-cd` initiative, after [`cd-agent.md`](cd-agent.md). The CD agent's own AppRoles
([0020](../decisions/0020-automation-identity-and-access-scope/revision-000.md))
couldn't be scoped until OpenBao holds real credentials to build policies
against — which it now does. The project also turns the runbook that hands each job its credentials into one command, and rotates each `secret_id` with it.

## Scope

The four AppRoles `cd-agent-deploy`, `cd-agent-rotation`, `cd-agent-freshness` and `cd-agent-snapshot`, their policies, and their CIDR binding; a command run from the operator host that delivers one job's credential files to `cd_agent`; and the rotation of a job's `secret_id` using the same command. Not in scope: the host itself ([`cd-agent.md`](cd-agent.md)) and retiring `controller`'s standing AppRole ([`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)).

## Decision

Implements [ADR 0020 revision 001 (Automation identity scope)](../decisions/0020-automation-identity-and-access-scope/revision-001.md), `approved`.

It also carries out the `secret_id` handoff of
[ADR 0047 (First-credential bootstrap)](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md),
`approved`: a response-wrapped value requested through `vault-bootstrap`,
carried on SSH stdin and unwrapped once on `cd_agent`. The wrapping call
needs the `vault-bootstrap` AppRole's `secret_id`, typed at a hidden prompt,
so the command is run by a person and is not unattended.
[`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md) names that revision, so it stays `approved` when this project closes. How
[ADR 0020 revision 1 (Automation identity scope)](../decisions/0020-automation-identity-and-access-scope/revision-001.md)
leaves the rotation cadence to a project is settled in Stage 5.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | `cd-agent-deploy` / `cd-agent-rotation` / `cd-agent-freshness` / `cd-agent-snapshot` AppRoles, CIDR-bound | In progress | both roles exist with the policies in ADR 0020 revision 001, each bound to `cd_agent`'s fixed IP |
| 2 | Jobs read their credential where it is delivered | In progress | a job's unit names its credentials directory, and `tools/` and the `secrets` role log in to OpenBao and resolve `main-domain` from it |
| 3 | Jobs verify OpenBao against a delivered root cert | In progress | `tools/` uses a `step-ca-root.crt` delivered to the credentials directory, and the `secrets` role fails when a delivered copy differs from the root it just fetched |
| 4 | Deliver a job's credentials | Not started | one command writes a job's `openbao-controller-secret-id`, `openbao-controller-role-id`, `main-domain` and `step-ca-root.crt` into its credentials directory with the owner and modes the job expects, and the job logs in |
| 5 | Rotate a `secret_id` | Not started | the same command adds a new `secret_id`, a login with it is confirmed, and the old one is destroyed by its accessor, with no failed job run in between |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — AppRoles

Four CIDR-bound AppRoles, per the
[decision](../decisions/0020-automation-identity-and-access-scope/revision-001.md):
`cd-agent-deploy` (read on `hosts/*` and `cloud_credentials/leaf/*`,
`create` but not `update` on `hosts/*`), `cd-agent-rotation`
(create/update on both `cloud_credentials/leaf/*` and
`cloud_credentials/rotation/*`, nothing under `hosts/*`) and
`cd-agent-freshness` (read-only on `cloud_credentials/leaf/*`,
`cloud_credentials/rotation/*` and `hosts/all/telegram/*`) and
`cd-agent-snapshot` (read on `sys/storage/raft/snapshot` and six named
snapshot-push leaf paths) — a compromised deploy run shouldn't be able
to reach rotation-tier credentials, the freshness check shouldn't be able
to write any, and the snapshot job shouldn't be able to read any other
leaf.

The four policies and the role-creation runbook are in
[`openbao-cd-agent-approles.md`](../topics/secrets/openbao-cd-agent-approles.md).
What remains needs the running host: creating the roles with `cd_agent`'s fixed
address (`192.168.30.3`) as both CIDR binds. Delivering each job's files, and
the `secret_id` rotation cadence, are Stages 4 and 5.

### Stage 2 — Credential location

A CD agent job's clean checkout has no `ansible/files/secrets/`, where the
`secrets` role and `tools/utils/repo.py` read `main-domain` and the
controller AppRole's `role_id` and `secret_id`. `HOMELAB_SECRETS_DIR`, an
absolute path set in the job's unit to its credentials directory
(`/etc/cd-agent/credentials/<job>/`), moves that cache; unset, it stays in
the checkout, so operator runs are unchanged. The delivered files keep the
names the readers already use: `main-domain`, `openbao-controller-role-id`
and `openbao-controller-secret-id`. See
[`openbao-cd-agent-approles.md`](../topics/secrets/openbao-cd-agent-approles.md).

### Stage 3 — Root cert trust

A job has no SSH key to `security`, so it cannot fetch step-ca's root cert
as [revision 0](../decisions/0022-controller-trust-in-the-secrets-store-tls/revision-000.md)
does. [Revision 1](../decisions/0022-controller-trust-in-the-secrets-store-tls/revision-001.md)
has the root, which is public, delivered to each job's credentials directory
as `step-ca-root.crt`. `cloud_credentials` uses it when it exists, and a run of
the `secrets` role that has both that file and a freshly fetched root fails
when they differ. The project's `also_implements:` names that revision, which
is set `accepted` in the PR that closes the project.

### Stage 4 — Delivery

For one job: request a wrapped `secret_id` for its AppRole, send the
wrapping token to `cd_agent` over SSH stdin, unwrap it there into the job's
`0400` file, and write the other three files, which are not secret, beside
it. A job's second `secret_id`, such as `cd-agent-deploy`'s for
`redeploy-storage` ([ADR 0074 (Job chaining)](../decisions/0074-following-one-automation-job-with-another-under-a-different-identity/revision-000.md)),
is the same command for another job's directory. The files and their names
are in
[`openbao-cd-agent-approles.md`](../topics/secrets/openbao-cd-agent-approles.md).

### Stage 5 — Rotation

An AppRole holds several `secret_id`s at once, so a rotation adds the new one,
confirms a login with it, then destroys the old one by its accessor.
Rotate when `cd_agent` is rebuilt or re-provisioned, when the operator host's
credentials change, on any suspected exposure, and every 90 days. The
`secret_id` has no expiry of its own, so a missed rotation is not an outage.

## Acceptance criteria

- [ ] All four AppRoles exist with the policies in ADR 0020 revision 001.
- [ ] Each is bound to `cd_agent`'s fixed IP (`secret_id_bound_cidrs` and `token_bound_cidrs`).
- [ ] `cd-agent-deploy` cannot read `cloud_credentials/rotation/*`, verified.
- [ ] `cd-agent-deploy` can create a missing `hosts/*` path and cannot update an existing one, verified.
- [ ] `cd-agent-rotation` can read no `hosts/*` path, verified.
- [ ] `cd-agent-freshness` can read the leaf, rotation and Telegram paths and write none of them, verified.
- [ ] `cd-agent-snapshot` can save a snapshot and read its six named leaf paths, and can read no other leaf path, verified.
- [ ] A job's unit sets `HOMELAB_SECRETS_DIR` to its credentials directory, verified.
- [ ] With it set, `tools/` and the `secrets` role log in and resolve `main-domain` from that directory and not from the checkout, and a relative value is refused, verified.
- [ ] With `step-ca-root.crt` in the credentials directory, `cloud_credentials` verifies OpenBao against it and does not fetch from `security`, and a file that is not a certificate is refused, verified.
- [ ] A `secrets` role run that has a delivered copy equal to the fetched root passes, one with a different copy fails naming the file, and one with no copy is unchanged, verified.
- [ ] One command delivers a job's four files, each with the owner and mode the job needs, and a job started afterwards logs in to OpenBao, verified.
- [ ] Each `secret_id` is delivered response-wrapped over stdin and unwrapped once on `cd_agent` into the job user's `0400` file, the wrapping token never appears in a process argument or a log, and a second unwrap of it fails, verified.
- [ ] A rotation leaves exactly one valid `secret_id` for that job and no failed run, verified.
- [ ] A step-ca root change is covered by re-running delivery for every job, and the deploy-side check then passes, verified.
- [ ] The rotation cadence and its triggers are in a topic doc.

## Risks

- A wrapping token has a short lifetime, so a delivery that stalls between the wrap and the unwrap has to be repeated.
- A wrong file name or mode breaks a job on its next run, so the command verifies each file before it reports success.

## Open items

- The `freshness` job's Gatus push token is a file the host needs besides the four credential files, written by hand today ([`cd-agent-host.md`](../topics/deploy/cd-agent-host.md#heartbeats)). Whether the delivery command also writes it is not decided.
- What reminds the maintainer that a 90-day rotation is due is not decided. The freshness job cannot read the `secret_id`'s age, since its policy grants no `auth/approle` capability.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
