---
id: PROJ-backup-archive-signing
title: "Backup Archive Signing"
type: project
status: not-started
blocked: false
summary: Sign each backup archive with a per-host key and make a restore refuse any archive whose signature does not verify against a key pinned in the repository, as ADR 0079 decides.
decision: ADR-0079/0
super_project: backup-archive-protection
track: authenticity
allowed_paths:
  - ansible/roles/backup_agent/**
  - ansible/roles/cloud_sync/**
  - ansible/roles/restore/**
  - ansible/roles/restore_discovery/**
  - ansible/scripts/restore_all.py
  - ansible/playbooks/restore*.yaml
  - ansible/tests/test_restore_all.py
  - ansible/tests/test_backup_plan.py
  - tools/tests/shell/check_freshness.bats
  - docs/topics/disaster-recovery/**
  - docs/topics/monitoring/gatus.md
  - docs/topics/engineering/molecule-testing.md
  - docs/architecture/backup-and-restore-data-flow.md
---

# Backup Archive Signing

A restore decrypts whatever sits under a host's prefix and picks the newest by the timestamp in its name, so an object written by anyone with a write path to SeaweedFS or a cloud target would be restored. This project makes each backup host sign its archives and makes a restore refuse an archive that is not signed by that host. It is staged because the first stage settles three assumptions about where the signing can run and how the signature travels, and the later stages build the signer, the relay and the check in that order, each on the one before.

## Scope

A signing key per backup host, generated on the host and never in the agent container, a unit that signs each archive and uploads a `.sig` beside it, `cloud_sync` carrying the signature with the archive, an `allowed_signers` file in this repository holding each host's public key, and a restore that verifies before it decrypts or applies anything and refuses, rather than falling back to an older archive, when the newest object fails. Then key rotation, the check that every backup host has a pinned key, and the freshness check's alert for an archive left unsigned.

Not in scope: rollback to an older genuine archive by deleting newer ones; the confidentiality of archives, which the GPG encryption provides; the OpenBao raft snapshot, which is restored by hand; protecting archives on `storage` from deletion by the host that wrote them, which is [ADR 0081 (On-site archive deletion)](../decisions/0081-protecting-on-site-backup-archives-from-their-writer/revision-000.md)'s; the cloud credentials' own freshness check, which is a different check from the hourly backup freshness check; the CI path filters and `test_inventory_sources.py`, which name `restore_all.py` and are not affected by a change inside it.

## Decision

Implements [ADR 0079 (Backup archive authenticity)](../decisions/0079-knowing-a-backup-archive-came-from-its-host/revision-000.md). The revision is `working` on three assumptions, which Stage 1 resolves. Rationale, threat model and rotation are there.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Resolve the assumptions and place `allowed_signers` | Not started | Each assumption in ADR 0079 is resolved and folded into its Context and the revision can be `approved`; this doc names where `allowed_signers` lives and how a single-app restore verifies (Open items 1 and 2), and `allowed_paths` covers every file stages 2 to 6 edit, widened in its own change before it is used |
| 2 | Sign each archive on its host | Not started | A Molecule scenario shows a `.sig` uploaded beside each archive by a unit on the host, signed with a root-only key that the agent container cannot read, and `backup.md` describes it |
| 3 | Relay the signature | Not started | A Molecule scenario relays an archive and its `.sig` to a target, and `cloud-sync.md` says each target's retention keeps a signature as long as its archive |
| 4 | Verify at restore | Not started | The unit tests listed under Validation in ADR 0079 pass, a restore of an archive filed under another host's prefix is refused in a Molecule scenario with two fake hosts, and `restore.md` and `backup-threat-model.md` describe the check and the refusal |
| 5 | Cover every backup host | Not started | A test fails when an app host has a backup schedule and no line in `allowed_signers`, and the restore has an explicit, logged override for archives written before signing |
| 6 | Rotate a key and alert on unsigned archives | Not started | A replaced host's old line carries `valid-before` and an archive it signed still verifies, and the hourly freshness check alerts on an archive left unsigned past a set time |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] A restore applies an archive only when its signature verifies against the pinned key for the host that wrote it.
- [ ] An archive that fails verification stops the restore, names the object and the reason, and does not select an older archive.
- [ ] No signing key is in the agent container, in the repository, or off its host.
- [ ] `allowed_signers` is read from the checkout the restore runs from, never from the place it fetches archives.
- [ ] A host with a backup schedule and no pinned key fails a test.
- [ ] An archive signed by a retired key still verifies, and one signed after the cutoff does not.
- [ ] Every behavior above is described in the backup and restore topic docs.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the linked revision's Decision; the backup GPG key and its handling; the SeaweedFS identities and their actions; the cloud targets' retention.
- **Relevant files and interfaces:** [`restore_all.py`](../../ansible/scripts/restore_all.py), whose `pick_latest` chooses the newest object and whose discovery decrypts it; `ansible/roles/backup_agent/templates/check-freshness.sh.j2`; `ansible/roles/cloud_sync/`.
- **Required checks:** `pre-commit run --all-files`, `uv run pytest` from `tools/` and the Molecule scenarios of the roles it edits.

## Risks

- A signature that arrives after its archive makes a restore see an unsigned object, so Stage 1 measures the lag before the check treats a missing `.sig` as a refusal.
- A restore of a host whose key was never pinned refuses until a pull request pins it, which adds a step to a first deploy.
- Archives written before signing carry no signature, so the override of Stage 5 is needed until the retention window has passed.

## Open items

1. Where `allowed_signers` lives in the repository. ADR 0079 says only that it is checked in and read from the checkout.
2. How a single-app restore verifies. ADR 0079 says it runs the same way as the batch restore, but the `restore` role takes an already-decrypted archive and never touches GPG or SeaweedFS, and the operator downloads and decrypts the object by hand, so the signature has to be checked before that step.
3. How the on-site `.sig` objects are pruned with their archives. ADR 0079 does not say, and `backup_agent` prunes by each app's retention with a plain delete ([ADR 0081 (On-site archive deletion)](../decisions/0081-protecting-on-site-backup-archives-from-their-writer/revision-000.md)).
4. How long an archive may stay unsigned before the freshness check alerts.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
