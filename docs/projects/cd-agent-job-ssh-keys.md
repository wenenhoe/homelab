---
id: PROJ-cd-agent-job-ssh-keys
title: CD Agent Job SSH Keys
type: project
status: not-started
blocked: true
blocked_reason: "ADR 0075 revision 0 is not approved."
summary: A per-job SSH key generated on the CD agent and authorized only on the hosts that job manages.
decision: ADR-0075/0
super_project: pull-based-cd
track: agent
---

# CD Agent Job SSH Keys

Carries out [ADR 0075](../decisions/0075-giving-an-automation-job-its-own-ssh-identity/revision-000.md): a CD agent job that reaches hosts holds its own key instead of the shared infrastructure key. It is staged because the role generates the key first, and the hosts authorize it only once the agent exists to connect from.

## Scope

In: key generation in the `cd_agent` role, the inventory reading a job's key, authorizing the public half on `storage` for `redeploy-storage`.

Not in: moving `deploy` off the shared key, an SSH certificate authority, delivering `secret_id` files ([`cd-agent-credential-delivery.md`](cd-agent-credential-delivery.md)).

## Decision

Implements [ADR 0075](../decisions/0075-giving-an-automation-job-its-own-ssh-identity/revision-000.md), revision 0.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The role generates a job's key, and the inventory reads it | Not started | A converge creates the key once, readable only by its job's user, and a job's `ansible_ssh_private_key_file` resolves to it |
| 2 | `storage` authorizes `redeploy-storage`'s public key from the agent's address only | Not started | `redeploy-storage` connects to `storage` with its own key, and from nowhere else |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] A converge generates each declared key once and never replaces it, verified in the role's Molecule verify.
- [ ] No job's user can read another job's key, verified.
- [ ] `storage` accepts `redeploy-storage`'s key from the agent's address and refuses it from another.

## Open items

- Where the public half is recorded for the operator to apply, and how it travels from the agent to that record.
- How the job's `known_hosts` entry for `storage` is established, since the unit's filesystem is read-only outside its state directory.
- Whether `deploy.yaml`'s `localhost` plays, which are not a connection to `storage`, still use the shared key's path.

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
