---
id: PROJ-openbao-auto-unseal
title: "OpenBao Auto-Unseal"
type: project
status: de-risking
blocked: false
summary: Seal OpenBao with an OCI KMS key so a reboot of `security` needs no operator, and let the maintenance job reboot that host again.
decision: ADR-0018/1
---

# OpenBao Auto-Unseal

Replaces manual Shamir unseal with a cloud KMS seal. Staged because the
decision's assumptions have to be settled by a throwaway spike before the
seal plugin reaches the production image, and because the migration of the
production node is a one-time step that needs the operator at the keyboard.

## Scope

The `ocikms` seal plugin in the OpenBao container, the seal stanza, the
KMS key and its restricted IAM user, the `init.py` and `unseal.py`
tooling, the offline handling of the new credential, and the topic docs
that describe the seal. The CI and Molecule OpenBao targets stay on Shamir.
Not in scope: a multi-node cluster, an HSM, and the snapshot path of
[ADR 0019 (OpenBao offsite snapshot)](../decisions/0019-openbao-offsite-snapshot-path/revision-000.md).

## Decision

Implements [ADR 0018 revision 1 (Secrets store unsealing)](../decisions/0018-unsealing-the-secrets-store-after-restart/revision-001.md),
still `working`, so this project is `de-risking` and only throwaway spikes
are allowed until its assumptions are resolved.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike: a throwaway OpenBao 2.7.1 with the `ocikms` plugin, a spike key and the narrowest IAM policy | Not started | each ADR 0018 revision 1 assumption is recorded as a fact in the ADR, and the restart with the DNS host stopped has been tried |
| 2 | Plugin delivery, seal stanza and tooling | Not started | the revision is `approved` and a Molecule scenario starts OpenBao with the plugin loaded and a stubbed seal |
| 3 | Production migration | Not started | `security` unseals itself after a restart, the offline copy of the credential exists, and a restore drill from that credential and a snapshot ends unsealed |
| 4 | Let maintenance reboot `security` | Not started | `patch_reboot_allowed` is true for `security`, `maintenance.yaml` checks the seal after the reboot, and the topic docs describe the seal |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — Spike

The spike's OpenBao, key, IAM user and credential live outside the
repository checkout and in a tenancy compartment of their own, and are
deleted afterwards; only facts go back into the ADR. It tries the narrowest
policy that lets init, migration and restart succeed, and a restart with
the `services` host stopped.

## Acceptance criteria

- [ ] `security` unseals after a restart with no operator, and the maintenance job reboots it.
- [ ] The KMS credential is held offline with the handling the Shamir shares have, and is in no repository, raft data or snapshot.
- [ ] A restore from a snapshot and that credential, on a fresh host, ends unsealed.
- [ ] The resulting behavior is described in a topic doc, not only here.

## Agent handoff

- **Allowed to change:** documentation only until ADR 0018 revision 1 is `approved`; Stage 1 produces nothing in the repository.
- **Must not change:** the Molecule OpenBao targets' Shamir seal, or any credential or key file in a commit.
- **Required checks:** `pre-commit run --all-files`.

## Risks

- The root key cannot be exported from OCI. A lost key or tenancy makes
  OpenBao and its snapshots unrecoverable; the decision records this and
  the drill is the check.
- The plugin may need to be built rather than downloaded, which adds a
  pinning decision.

## Open items

- Where the plugin binary is published for 2.7.x and how it is verified.
- Whether the tenancy's account type reclaims an idle key.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
