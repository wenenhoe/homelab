---
id: PROJ-openbao-auto-unseal
title: "OpenBao Auto-Unseal"
type: project
status: not-started
blocked: false
summary: Seal OpenBao with an OCI KMS key so a reboot of `security` needs no operator, and let the maintenance job reboot that host again.
decision: ADR-0018/1
---

# OpenBao Auto-Unseal

Replaces manual Shamir unseal with a cloud KMS seal. Staged because the
plugin and seal stanza, and the maintenance reboot, are separate reviewable
changes, and the migration of the production node is a one-time step that
needs the operator at the keyboard, so it is an acceptance criterion.

## Scope

The `ocikms` seal plugin in the OpenBao container, the seal stanza, the
KMS key and its restricted IAM user, the `init.py` and `unseal.py`
tooling, the offline handling of the new credential, and the topic docs
that describe the seal. The CI and Molecule OpenBao targets stay on Shamir.
Not in scope: a multi-node cluster, an HSM, and the snapshot path of
[ADR 0111 (Secrets store recovery)](../decisions/0111-recovering-the-secrets-store-from-total-loss/revision-000.md).

## Decision

Implements [ADR 0018 revision 1 (Secrets store unsealing)](../decisions/0018-unsealing-the-secrets-store-after-restart/revision-001.md),
still `working`, so this project is `not-started` or `de-risking` until the revision is `approved`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Plugin delivery, seal stanza and tooling | Not started | a Molecule scenario starts OpenBao with the plugin loaded and a stubbed seal |
| 2 | Let maintenance reboot `security` | Not started | `patch_reboot_allowed` is true for `security`, `maintenance.yaml` checks the seal after the reboot, and the topic docs describe the seal |

Stage status is `Not started`, `In progress`, or `Done`.

### The migration

Run by the operator on `security` once the plugin and seal stanza are merged: migrate the seal, keep an offline copy of the credential, then restore from that credential and a snapshot on a fresh host.

## Acceptance criteria

- [ ] `security` unseals after a restart with no operator, and the maintenance job reboots it.
- [ ] The KMS credential is held offline with the handling the Shamir shares have, and is in no repository, raft data or snapshot.
- [ ] A restore from a snapshot and that credential, on a fresh host, ends unsealed.
- [ ] After the migration, `security` unseals itself after a restart, and a restore drill from the offline credential and a snapshot ends unsealed.
- [ ] The resulting behavior is described in a topic doc, not only here.

## Agent handoff

- **Allowed to change:** documentation only until ADR 0018 revision 1 is `approved`. The migration is run by the operator, not by a pull request.
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
