---
id: PROJ-cd-agent-rotation
title: CD Agent Rotation
type: project
status: building
blocked: false
summary: Chained jobs on the CD agent, and the monthly leaf-credential rotation that uses them.
decision: ADR-0074/0
super_project: pull-based-cd
track: agent
---

# CD Agent Rotation

Carries out [ADR 0074](../decisions/0074-following-one-automation-job-with-another-under-a-different-identity/revision-000.md): one CD agent job starting another that holds different credentials, and the first chain it exists for, a monthly leaf-credential rotation followed by a redeploy of `storage`. It is staged because the mechanism lands in the `cd_agent` role first, and the jobs that use it wait on credentials another project delivers.

## Scope

In: the chaining mechanism in the `cd_agent` role; the rotation job and `redeploy-storage` in the agent's inventory; a native `rclone` on the host.

Not in: the AppRoles and their delivery ([`cd-agent-approles.md`](cd-agent-approles.md)); rotating the three rotation-tier credentials, which stays human-attended; failure alerts ([ADR 0072](../decisions/0072-detecting-scheduled-jobs-that-stop-running/revision-000.md)).

## Decision

Implements [ADR 0074](../decisions/0074-following-one-automation-job-with-another-under-a-different-identity/revision-000.md), revision 0.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Chaining in the `cd_agent` role: successors, jobs with no timer, and chain validation | In progress | A role run builds a chain whose successor runs as its own user after its predecessor ends, after a success and after a failure, and refuses a cycle, a successor that is no job, and a job nothing starts |
| 2 | The rotation job and `redeploy-storage`, defined in the agent's inventory | Not started | A rotation run replaces the six leaf credentials monthly, and `storage` is running the new write key before its next `cloud_sync`, without a manual deploy |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 2 — rotation and `redeploy-storage`

Rotation covers the six leaf credentials only, as rotate-and-revoke: `create_leaf_keys --rotate both` per provider creates a new key, verifies it over rclone, and only then revokes the old one ([ADR 0023](../decisions/0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md)). The three rotation-tier credentials stay human-attended, with the freshness check as the prompt: B2's is minted from a master key the code never stores, R2's needs a token minted in the Console first, and OCI's is a hard cutover with no rollback ([`rotation.md`](../topics/secrets/cloud-credentials/rotation.md)).

`storage` takes the write leaf only when `deploy.yaml` re-renders its `rclone.conf`, and the deploy job acts only on a changed commit, so `redeploy-storage` follows the rotation job. It runs `deploy.yaml --limit storage,localhost` without `--on-change`, as its own user. Rotation is scheduled for the 8th at 02:00, so the redeploy finishes before `cloud_sync`'s 06:00 run and clear of the maintenance runs. The host needs a native `rclone` at the version `cloud_sync` uses, since the verification follows production's request sequence.

`create_leaf_keys --rotate` takes one provider, and a job runs one command, so the rotation job needs a repo entry point that rotates each provider in turn. It has to carry on after one provider fails: a failure after a rotation still leaves `storage` stale, which is why the chain starts the redeploy however the rotation ends.

## Acceptance criteria

- [ ] A successor runs as its own user, in its own checkout, after a predecessor that succeeds and after one that fails, verified in the role's Molecule verify.
- [ ] The role refuses a cycle, a successor that is no job, successors that are not a list, and a job with no timer and no predecessor, verified.
- [ ] The rotation job replaces the six leaf credentials monthly, and `storage` is running the new write key before its next `cloud_sync` without a manual deploy.

## Open items

- Neither job can log in to OpenBao until a job can read its credential from where it is delivered; see [`cd-agent-approles.md`](cd-agent-approles.md)'s open items.
- `redeploy-storage` needs its own user, SSH key and `secret_id`, a second valid `secret_id` of the `cd-agent-deploy` AppRole, delivered like the other jobs'.

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
