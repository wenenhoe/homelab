---
id: PROJ-cd-agent-approles
title: CD Agent AppRoles
type: project
status: building
blocked: false
summary: Four CIDR-bound AppRoles for the CD agent (deploy, rotation, freshness and snapshot).
decision: ADR-0020/1
also_implements: [ADR-0022/1]
super_project: pull-based-cd
track: credentials
---

# CD Agent AppRoles

Second of three projects in the `pull-based-cd` initiative, after [`cd-agent.md`](cd-agent.md). The CD agent's own AppRoles
([0020](../decisions/0020-automation-identity-and-access-scope/revision-000.md))
couldn't be scoped until OpenBao holds real credentials to build policies
against — which it now does.

## Scope

The four AppRoles `cd-agent-deploy`, `cd-agent-rotation`, `cd-agent-freshness` and `cd-agent-snapshot`, their policies, and their CIDR binding. Not in scope: the host itself ([`cd-agent.md`](cd-agent.md)) and retiring `controller`'s AppRole ([`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)).

## Decision

Implements [ADR 0020, revision 001](../decisions/0020-automation-identity-and-access-scope/revision-001.md), `approved`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | `cd-agent-deploy` / `cd-agent-rotation` / `cd-agent-freshness` / `cd-agent-snapshot` AppRoles, CIDR-bound | In progress | both roles exist with the policies in ADR 0020 revision 001, each bound to `cd_agent`'s fixed IP |
| 2 | Jobs read their credential where it is delivered | In progress | a job's unit names its credentials directory, and `tools/` and the `secrets` role log in to OpenBao and resolve `main-domain` from it |
| 3 | Jobs verify OpenBao against a delivered root cert | In progress | `tools/` uses a `step-ca-root.crt` delivered to the credentials directory, and the `secrets` role fails when a delivered copy differs from the root it just fetched |

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
address (`192.168.30.3`) as both CIDR binds, and delivering each `secret_id`.

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
- [ ] Each `secret_id` is delivered response-wrapped over stdin and unwrapped once on `cd_agent` into the job user's `0400` file, and a second unwrap of the same token fails, verified.

## Open items

- Delivering the files (operator host to `cd_agent`, [ADR 0047](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md)) is not automated; a job fails on every run until its files are there.

- The `secret_id` rotation cadence ([ADR 0020 revision 1](../decisions/0020-automation-identity-and-access-scope/revision-001.md) leaves it to this project) is not decided.

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
