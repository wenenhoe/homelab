---
id: PROJ-cd-agent-controller-approle-retirement
title: Retire controller's Standing AppRole
type: project
status: not-started
blocked: false
summary: Delete controller's AppRole; admin access mints short-lived tokens on demand.
decision: ADR-0047/0
super_project: pull-based-cd
depends_on:
  - project: PROJ-cd-agent
    reason: the AppRole is retired only once the agent host runs the jobs and its own AppRoles are live and proven
---

# Retire controller's Standing AppRole

Last of two projects in the `pull-based-cd` initiative: once the [agent host](cd-agent.md) and its AppRoles are live and proven, `controller`'s standing AppRole is deleted outright.

## Scope

Deleting `controller`'s Era A AppRole and its policy, and the on-demand token minting that replaces it. Not in scope: the agent host and its AppRoles ([`cd-agent.md`](cd-agent.md)).

## Decision

Implements [ADR 0047 (First-credential bootstrap)](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md), `approved`: how `controller` authenticates to mint on-demand tokens once its standing AppRole is gone.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Move the credential-expiry check to the agent: remove the weekly `check-freshness` user timer from `controller` | Not started | The timer is gone from `controller` and a `credential-expiry` run on the CD agent that fails, with OpenBao sealed or unreachable, alerts as a missed heartbeat |
| 2 | Run the snapshot push from `cd-agent-snapshot` instead of `snapshot-push.sh` on `controller` | Not started | The push runs from the agent's job and no longer from `controller`; ADR 0111's revision for the unattended push is in place |
| 3 | Issue `controller`'s client certificate from a second step-ca provisioner and create the `cert` role | Not started | Admin and debug access logs in with a step-ca client certificate bound to `controller`'s common name, organizational unit and fixed address, and receives a short-lived token; the `cert` role refuses the same common name when the original provisioner signs it |
| 4 | Delete `controller`'s Era A AppRole and its policy, and the topic docs and catalog entries that describe them | Not started | `controller` holds no AppRole `secret_id`, and no topic doc or catalog entry still describes the AppRole or how to re-issue its `secret_id` |

Stage status is `Not started`, `In progress`, or `Done`.

### How the stages run

Once the agent host and its AppRoles are live and proven, in the order of the stages.

1. The same check now runs from `cd-agent-credential-expiry`, and the timer logs in with the AppRole being deleted. The agent's `credential-expiry` job pushes a heartbeat on success ([ADR 0072 (Job heartbeats)](../decisions/0072-detecting-scheduled-jobs-that-stop-running/revision-000.md)), so a run that fails, or cannot reach OpenBao, is reported as a missed heartbeat; the timer on `controller` has no such alert. The timer lives in `tools/cloud_credentials/systemd/`.
2. `controller`'s policy grants the `sys/storage/raft/snapshot` read the old script uses, and deleting the AppRole removes it.
3. The second step-ca provisioner is added by hand, with its template checked in and its password held offline and never stored in OpenBao. The certificate is issued once with it and renewed over mTLS, and a `cert` role is bound to its common name, the organizational unit the template stamps, and its fixed address ([ADR 0047 (First-credential bootstrap)](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md)).
4. The AppRole's `role_id` and `secret_id` files go with it, as ADR 0047 states, together with [`openbao-auth.md`](../topics/secrets/openbao-auth.md), including its "Re-issuing the secret ID" section, and the `openbao-controller-role-id` and `openbao-controller-secret-id` entries in `secret_catalog.yaml`, in the same PR.

## Acceptance criteria

- [ ] `controller`'s AppRole, its `secret_id`, and its policy are deleted.
- [ ] Admin and debug access logs in with a step-ca client certificate from the second provisioner, bound to `controller`'s common name, organizational unit and fixed address, and receives a short-lived token, per ADR 0047.
- [ ] The `cert` role refuses the same common name when the original provisioner signs it, verified.
- [ ] The `check-freshness` user timer is gone from `controller`, and the snapshot push runs from `cd-agent-snapshot`.
- [ ] A `credential-expiry` run on the CD agent that fails, with OpenBao sealed or unreachable, alerts as a missed heartbeat.
- [ ] No topic doc or catalog entry still describes `controller`'s AppRole or how to re-issue its `secret_id`.

## Open items

- The `cert` role's policy. The human-attended workflows that still need OpenBao from `controller` (generating and rotating secrets by hand, creating cloud leaf credentials the first time) decide it. It should be no wider than `controller.hcl` is today, minus what moved to `cd_agent`.
- A client certificate and key on `controller` is itself a standing credential, renewable for as long as the renewal runs. ADR 0047 treats it as narrower than a `secret_id`, since it is bound to a name, a unit and an address and expires unless renewed. If renewal lapses, re-issuing it needs the offline provisioner password. If the goal is no standing credential at all, this design does not meet it.

- Where the snapshot write credential lives. [ADR 0111 (Secrets store recovery)](../decisions/0111-recovering-the-secrets-store-from-total-loss/revision-000.md) states that the snapshot write leaf exists only on `security` and that a failed push fails in front of the operator. Stage 2 moves the push to an unattended `cd-agent-snapshot` job on `cd_agent`, which then holds those keys. ADR 0111 is `accepted`, so a new revision restates both invariants before stage 2 is built.
- Rebuilding `security` after the AppRole is gone. [ADR 0099 (Rebuilding security from nothing)](../decisions/0099-rebuilding-security-from-nothing/revision-000.md) logs in as `controller`'s AppRole in Play 0 to read step-ca's root certificate and passwords before step-ca exists. Once the login is a step-ca certificate, a restore needs a certificate from the authority it is restoring. The chain from a restored OpenBao to a working login has to be shown to close, including when the certificate has lapsed and renewing it needs the offline provisioner password, before stage 4 deletes the AppRole. ADR 0099 gets a revision if its sequence changes.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
