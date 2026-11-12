---
id: PROJ-backup-archive-retention-lock
title: "Backup Archive Retention Lock"
type: project
status: not-started
blocked: false
summary: Lock the on-site backup bucket in compliance mode so the host that wrote an archive cannot delete it, and expire superseded versions once their lock ends, as ADR 0081 decides.
decision: ADR-0081/0
super_project: backup-archive-protection
allowed_paths:
  - docker/seaweedfs/**
  - ansible/roles/seaweedfs_bucket/**
  - ansible/roles/backup_agent/molecule/**
  - ansible/roles/cloud_sync/molecule/**
  - ansible/tests/test_backup_plan.py
  - .config/.trivyignore
  - docs/topics/disaster-recovery/**
  - docs/topics/engineering/molecule-testing.md
---

# Backup Archive Retention Lock

An archive on `storage` can be deleted by the host that wrote it, because its identity holds `Write` on its prefix and a delete is a write. This project turns on versioning and Object Lock in compliance mode for the backup bucket, with a default retention equal to the shared backup retention, and runs the lifecycle jobs that remove what the apps have pruned once its lock has ended. It is staged because the worker, the bucket and the lifecycle rules are separate reviewable changes, and the live bucket is converted in place by hand after the code that declares it is merged.

## Scope

Versioning and a compliance-mode default retention on the backup bucket, declared by the `seaweedfs_bucket` role; an admin server and a worker restricted to `s3_lifecycle,vacuum` beside SeaweedFS in its network namespace; bucket-wide lifecycle rules that expire a noncurrent version one day after it became noncurrent, remove a delete marker with nothing behind it, and abort an incomplete multipart upload after one day; the check that no app's retention is shorter than the lock window; the Trivy ignore entry that records versioning as suspended on purpose, which no longer holds; a signal for a stopped worker and one for the volume's free space; and the one-time conversion of the live bucket. The disaster-recovery topic docs then describe the lock and the narrowed residual risk.

Not in scope: the agents' pruning, which stays a plain delete; the identities, which gain no action; the filer API, `weed shell` and the `storage` host; the cloud copies, whose lock and lifecycle stay provider-native; which retention the apps use; archives written after a compromise, which is [`backup-archive-signing.md`](backup-archive-signing.md)'s.

## Decision

Implements [ADR 0081 (On-site archive deletion)](../decisions/0081-protecting-on-site-backup-archives-from-their-writer/revision-000.md). The revision is `working` on four assumptions; the project does not start building until they are resolved and it is `approved`. Rationale, the threat model and what was checked on the pinned image are there.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Run the admin and worker beside SeaweedFS | Not started | A Molecule scenario on the SeaweedFS target shows the worker registering `s3_lifecycle` and `vacuum` over loopback, no container on `caddy-proxy` reaching the admin, and the admin API unrouted through Caddy |
| 2 | Declare the locked bucket | Not started | `seaweedfs_bucket` creates a bucket with versioning, Object Lock and a compliance default retention of `backup_defaults.retention_days`, is idempotent on it, a unit test over `backup_plan` fails when an app's retention is below that window, the `identity_scoping` scenario shows a scoped identity's delete of a fresh archive by `VersionId` refused and the bucket-admin identity's too, and the `AWS-0090` entry in `.trivyignore` is removed |
| 3 | Declare the lifecycle rules and the signal | Not started | A Molecule scenario drives the lifecycle job on demand against a target with a short explicit retention, and an expired superseded version and an orphaned marker are removed while a locked version is not; the stopped-worker signal and the free-space signal each fire in their tests |

Stage status is `Not started`, `In progress`, or `Done`.

### The conversion

Run by the operator on `storage`, through the S3 API, once the stages are merged: versioning back on, then the lock and the default retention. A rebuilt `storage` host takes the role's create path instead. Archives written before the conversion carry no lock and age out as they do now.

## Acceptance criteria

- [ ] No S3 identity, the bucket-admin identity included, can remove or shorten an archive version before its lock ends.
- [ ] No backup identity holds an action that sets retention or bypasses it.
- [ ] An archive's data is removed only after it has been pruned and its lock has ended.
- [ ] The admin API is not routed through Caddy and no container on `caddy-proxy` reaches it.
- [ ] No app's retention is shorter than the lock window, and a test fails when one is.
- [ ] A stopped worker is noticed before the volume fills.
- [ ] The volume's free space running short is noticed before the volume fills.
- [ ] The live bucket reports versioning and a compliance default retention after the conversion, and each app's next archive carries the lock.
- [ ] The conversion runbook step is in `backup.md`.
- [ ] The backup and threat-model topic docs describe the lock and the narrowed residual risk.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced. The conversion is run by the operator on `storage`, not by a pull request.
- **Must not change:** the linked revision's Decision; the backup identities' actions; the `backup_agent` prune; the cloud targets' lock and lifecycle.
- **Relevant files and interfaces:** [`compose.yaml.j2`](../../docker/seaweedfs/compose.yaml.j2) and [`s3-identity.json.j2`](../../docker/seaweedfs/configs/s3-identity.json.j2); `ansible/roles/seaweedfs_bucket/`, whose `default` scenario holds the probe that asserts a plain delete leaves no marker and which changes with this project.
- **Required checks:** `pre-commit run --all-files`, `uv run pytest` from `tools/` and the Molecule scenarios of the roles it edits.

## Risks

- A compliance lock cannot be undone for an object that already has it, and lowering the default retention affects only later uploads, so a wrong retention at the conversion costs disk until it expires.
- A stopped worker means no lifecycle removal, so the bucket grows until the signal fires and the volume must have room for the retention window plus two days of the largest app's archives.
- This project and [`backup-archive-signing.md`](backup-archive-signing.md) edit the same backup and restore topic docs, and both may add a test over `backup_plan`, so whichever merges second rebases on the other.

## Open items

1. Which collection or API call declares the lifecycle rules, since `amazon.aws` 11.5.0 has no lifecycle module.
2. How the on-site `.sig` objects that [`backup-archive-signing.md`](backup-archive-signing.md) adds are removed when their archive is: ADR 0081 does not mention them, and the lifecycle rules above act on noncurrent versions and delete markers.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
