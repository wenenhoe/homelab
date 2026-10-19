---
id: PROJ-cd-agent-job-ssh-keys
title: CD Agent Chained Jobs, Rotation and Job SSH Keys
type: project
status: building
blocked: false
summary: Chained jobs on the CD agent, the monthly leaf-credential rotation that uses them, and the per-job SSH key that its redeploy needs.
decision: ADR-0074/0
also_implements: [ADR-0075/0]
super_project: pull-based-cd
track: agent
---

# CD Agent Chained Jobs, Rotation and Job SSH Keys

Carries out [ADR 0074 (Job chaining)](../decisions/0074-following-one-automation-job-with-another-under-a-different-identity/revision-000.md): one CD agent job starting another that holds different credentials, and the first chain it exists for, a monthly leaf-credential rotation followed by a redeploy of `storage`. It also carries out [ADR 0075 (Job SSH identity)](../decisions/0075-giving-an-automation-job-its-own-ssh-identity/revision-000.md): a job that reaches hosts holds its own key instead of the shared infrastructure key, which `redeploy-storage` needs. It is staged because the chaining mechanism lands in the `cd_agent` role first, the jobs that use it wait on credentials another project delivers, and the key is generated before `storage` authorizes it.

## Scope

In: the chaining mechanism in the `cd_agent` role; the rotation job and `redeploy-storage` in the agent's inventory; a native `rclone` on the host; key generation in the `cd_agent` role, the inventory reading a job's key, and authorizing the public half on `storage` for `redeploy-storage`.

Not in: the AppRoles and their delivery ([`cd-agent-approles.md`](cd-agent-approles.md)); rotating the three rotation-tier credentials, which stays human-attended; failure alerts ([ADR 0072 (Job heartbeats)](../decisions/0072-detecting-scheduled-jobs-that-stop-running/revision-000.md)); moving `deploy` off the shared key; an SSH certificate authority.

## Decision

Implements [ADR 0074 (Job chaining)](../decisions/0074-following-one-automation-job-with-another-under-a-different-identity/revision-000.md), `approved`, which gates this project. It also carries out [ADR 0075 (Job SSH identity)](../decisions/0075-giving-an-automation-job-its-own-ssh-identity/revision-000.md), `working` with one open assumption (`storage` sees the agent as `192.168.30.3`), named in `also_implements:`. Stages 3 and 4 do not start before that revision is `approved`, and Stage 3 is where its assumption is checked. Closing this project needs both revisions `accepted`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Chaining in the `cd_agent` role: successors, jobs with no timer, and chain validation | Done | A role run builds a chain whose successor runs as its own user after its predecessor ends, after a success and after a failure, and refuses a cycle, a successor that is no job, and a job nothing starts |
| 2 | The rotation job and `redeploy-storage`, defined in the agent's inventory. A real run waits on Stages 3 and 4 for `redeploy-storage`'s key | In progress | A rotation run replaces the six leaf credentials monthly, and `storage` is running the new write key before its next `cloud_sync`, without a manual deploy |
| 3 | The role generates a job's key, and the inventory reads it. Starts once ADR 0075 is `approved` | Not started | A converge creates the key once, readable only by its job's user, and a job's `ansible_ssh_private_key_file` resolves to it |
| 4 | `storage` authorizes `redeploy-storage`'s public key from the agent's address only | Not started | `redeploy-storage` connects to `storage` with its own key, and from nowhere else; ADR 0075 can be `accepted` |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 2 — rotation and `redeploy-storage`

Rotation covers the six leaf credentials only, as rotate-and-revoke: `create_leaf_keys --rotate both` per provider creates a new key, verifies it over rclone, and only then revokes the old one ([ADR 0023 (Cloud credential logic reuse)](../decisions/0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md)). The three rotation-tier credentials stay human-attended, with the freshness check as the prompt: B2's is minted from a master key the code never stores, R2's needs a token minted in the Console first, and OCI's is a hard cutover with no rollback ([`rotation.md`](../topics/secrets/cloud-credentials/rotation.md)).

`storage` takes the write leaf only when `deploy.yaml` re-renders its `rclone.conf`, and the deploy job acts only on a changed commit, so `redeploy-storage` follows the rotation job. It runs `deploy.yaml --limit storage,localhost` without `--on-change`, as its own user. Rotation is scheduled for the 8th at 02:00, so the redeploy finishes before `cloud_sync`'s 06:00 run and clear of the maintenance runs. The host needs a native `rclone` at the version `cloud_sync` uses, since the verification follows production's request sequence.

The rotation job runs `python -m cloud_credentials.rotate_leaf_keys`, which rotates each provider in turn ([`rotation.md`](../topics/secrets/cloud-credentials/rotation.md#rotation)). The host has a native `rclone` at the version `cloud_sync` runs ([`cd-agent-host.md`](../topics/deploy/cd-agent-host.md)); without one, verification cannot run, and each run leaves a new, unrevoked key at the provider. Both jobs are defined in the agent's inventory ([`cd-agent-host.md`](../topics/deploy/cd-agent-host.md)). What is left of the stage is a real run, which needs the open items below settled, the role applied, and Stages 3 and 4 done for `redeploy-storage`'s key.

## Acceptance criteria

- [ ] A successor runs as its own user, in its own checkout, after a predecessor that succeeds and after one that fails, verified in the role's Molecule verify.
- [ ] The role refuses a cycle, a successor that is no job, successors that are not a list, and a job with no timer and no predecessor, verified.
- [ ] The rotation job replaces the six leaf credentials monthly, and `storage` is running the new write key before its next `cloud_sync` without a manual deploy.
- [ ] A converge generates each declared key once and never replaces it, verified in the role's Molecule verify.
- [ ] No job's user can read another job's key, verified.
- [ ] `storage` accepts `redeploy-storage`'s key from the agent's address and refuses it from another.

## Open items

- Neither job can log in to OpenBao until its credentials are in its credentials directory; delivering them is [`cd-agent-approles.md`](cd-agent-approles.md)'s.
- `redeploy-storage` needs its own user, SSH key and `secret_id`, a second valid `secret_id` of the `cd-agent-deploy` AppRole, delivered like the other jobs'. The SSH key is not among [`cd-agent-approles.md`](cd-agent-approles.md)'s four files, and `ansible/inventory/inventory.yaml` reads the key from `~/.ssh/proxmox_vm_servers`; Stages 3 and 4 give the job its own key.
- Where the public half is recorded for the operator to apply, and how it travels from the agent to that record.
- How the job's `known_hosts` entry for `storage` is established, since the unit's filesystem is read-only outside its state directory.
- Whether `deploy.yaml`'s `localhost` plays, which are not a connection to `storage`, still use the shared key's path.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
