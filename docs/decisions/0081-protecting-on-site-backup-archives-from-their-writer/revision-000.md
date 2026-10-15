---
id: ADR-0081
revision: 0
type: adr
title: Protecting on-site backup archives from the host that wrote them
short: On-site archive deletion
solution: Object Lock in compliance mode on the backup bucket, with lifecycle rules run by an admin and worker beside SeaweedFS removing superseded versions once their lock ends
summary: How an archive on `storage` survives a delete requested by the host that wrote it, and how the bucket still shrinks back to its retention window afterwards.
topic: backup-recovery
status: working
related: [ADR-0006, ADR-0010, ADR-0068, ADR-0079]
---

# 0081. Protecting on-site backup archives from the host that wrote them

## Problem

An archive that has landed on `storage` has to stay stored, readable and
unaltered for a fixed window, whatever the host that wrote it asks of
SeaweedFS afterwards. Once that window and the app's retention have both
passed, the archive has to be removed for real, so the bucket's size follows
retention and not the history of every archive ever written.

## Context

[`backup-threat-model.md`](../../topics/disaster-recovery/backup-threat-model.md)
bounds a compromised app host to its own prefix on SeaweedFS and accepts that
it can tamper with its own archives there. Deleting them is part of that: the
host's identity holds `Write`, `Read`, `List` and `Tagging` on its prefix
([`s3-identity.json.j2`](../../../docker/seaweedfs/configs/s3-identity.json.j2)),
and a delete is a write. The cloud copies do not have this property, because
`cloud_sync` only ever adds objects and each provider enforces its own lock and
lifecycle ([ADR 0010 (Offsite copy deletion)](../0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md)).
The on-site copy is the first one a restore reads
([ADR 0079 (Backup archive authenticity)](../0079-knowing-a-backup-archive-came-from-its-host/revision-000.md)),
so it is the copy that should not be the weak one.

**Threat model.** The adversary is the one the threat model already names: a
compromised app host holding its SeaweedFS identity. It does not hold the
bucket-admin credential and has no path to `storage` itself, which stays out of
scope. The asset is the on-site archives it wrote before the compromise. The
attack path is a delete against its own prefix, by object name or by version.

Each `backup_agent` prunes by retention with a plain delete. On a
versioned bucket a plain delete adds a delete marker and keeps the data, so
nothing frees space unless something else removes superseded versions. The
bucket currently has versioning suspended, which makes the prune free space
([`backup.md`](../../topics/disaster-recovery/backup.md#bucket-creation)), and
also means no lock is possible: Object Lock needs versioning on.

Checked on the pinned SeaweedFS image, in a throwaway server run with the same
flags and the same identity shapes as production:

- A backup identity can delete its own version by `VersionId` on a versioned
  bucket. Versioning alone protects nothing.
- A bucket with Object Lock and a default retention stamps every new object,
  including a multipart upload from the scoped identity. In compliance mode a
  delete by `VersionId` is refused for the backup identity and for the
  bucket-admin identity alike, with or without the governance-bypass header. In
  governance mode the bucket-admin identity can delete with the bypass header.
- The backup identity cannot choose its own retention on upload: a request that
  carries lock headers is refused. Its uploads take the bucket default.
- Once a version's lock has ended, the backup identity can delete it again.
- A lifecycle rule is accepted and stored. Its `s3_lifecycle` job, run by
  `weed worker` against `weed admin`, removed noncurrent versions down to a rule's
  count, left versions still under a lock untouched, and removed a delete marker
  that had nothing behind it. The job runs once a day by default and can be run
  on demand through the admin API.
- The day-based rule removes what it should and no earlier. On a bucket with a
  one-day compliance default and a one-day noncurrent rule, with the clock moved
  forward in steps, a run at the start and a run twelve hours on removed nothing.
  At twenty-five hours a version superseded at the start, and a version behind a
  delete marker, were removed, and an incomplete multipart upload was aborted. A
  version superseded at twelve hours was still there at twenty-five and gone at
  thirty-seven. The delete marker left alone by that removal went on the next run
  and a current version was never touched.
- The clients behave as they do without a lock. A multipart upload from the
  minio Python SDK as the backup identity took the default retention. A bulk
  delete of the oldest archive left a marker, after which a listing, `rclone lsf
  --max-age`, `rclone lsjson` and `rclone copy` 1.75.0 showed only the remaining
  archives, and the same name could be written again.
- The admin binds its HTTP and gRPC ports to loopback only. A worker started
  with `-jobType=s3_lifecycle,vacuum` in the same network namespace as the
  server connected over loopback and registered those two jobs. A peer namespace
  on the same subnet reached the S3, filer and master ports and was refused on
  the admin's two.
- With a worker connected, the master's own vacuum sweep is switched off and the
  worker's `vacuum` job takes over; the master's sweep comes back about half a
  minute after the worker disconnects. A worker started with only
  `s3_lifecycle,vacuum` registers only those two jobs.
- The filer HTTP API deletes a version that is still locked. The lock is
  enforced by the S3 layer only.
- `amazon.aws.s3_bucket` creates a bucket with Object Lock and a default
  retention, is idempotent on it, and changes the default retention in place. It
  refuses to enable Object Lock on an existing bucket, although the S3 call
  itself works on one and a bucket converted that way is then handled by the
  module as if it had been created with the lock.
- A listing as the backup identity returns current objects only, not superseded
  versions or delete markers. `rclone copy`, which `cloud_sync` runs with no age
  filter, copies every object it lists that the target lacks, so an app's on-site
  retention that outlasts a target's delete-after would be copied back to that
  target after it expired there
  ([`cloud-sync.md`](../../topics/disaster-recovery/cloud-sync.md)).

## Decision

- **Lock the bucket.** The backup bucket has versioning enabled and Object Lock
  enabled, with a default retention in compliance mode. The window is
  `backup_defaults.retention_days` ([ADR 0068 (Backup defaults)](../0068-where-per-app-backup-settings-get-their-defaults/revision-000.md)),
  so an archive is
  locked for as long as the shared retention says it is kept. An app cannot ask
  for a shorter retention than the window.
- **Leave pruning as it is.** `backup_agent` still prunes by each app's own
  retention with a plain delete. That makes the archive a noncurrent version
  behind a delete marker. It is not removed yet.
- **Expire what was pruned.** Bucket-wide lifecycle rules remove a noncurrent
  version one day after it became noncurrent, remove a delete marker with
  nothing behind it, and abort an incomplete multipart upload after one day. The
  lifecycle job skips a version whose lock has not ended, so an archive is
  removed only after both its prune and its lock are over. Stored data is
  therefore about the retention window plus two days; the marker's own removal
  takes one more daily run and frees nothing.
- **Run the jobs beside SeaweedFS.** An admin server and a worker restricted to
  `s3_lifecycle,vacuum` run next to the all-in-one server in the SeaweedFS
  stack, in its network namespace (`network_mode: service:seaweedfs`), so the
  admin's loopback listener is the boundary. The admin API is never routed
  through Caddy and is not reachable from outside the stack. The worker's vacuum job replaces the master's sweep.
- **Convert once, then declare.** The existing bucket is converted in place by
  one runbook step through the S3 API: versioning back on, then the lock and the
  default retention. A rebuilt `storage` host takes the module's create path.
  After either, `seaweedfs_bucket` declares the state and is idempotent on it.
  Archives written before the conversion carry no lock and age out as they do
  now.
- **Identities do not change.** Backup identities gain no action that sets
  retention or bypasses it, and the bucket-admin identity stays bucket-scoped.

## Alternatives considered

- **Governance mode.** It lets the bucket-admin identity delete with the bypass
  header, and that credential is held for bucket administration. Compliance
  binds every S3 identity, the administrator's included, which is the point of
  the lock. The cost is that nobody can shorten or remove a locked archive over
  S3 before its window ends.
- **Versioning without a lock.** The writer's identity deletes its own version
  by `VersionId`, so it protects only against a plain delete.
- **A timer on `storage` that deletes noncurrent versions.** It needs no extra
  processes and works with the lock, since it can only remove versions whose lock
  has ended. It loses because it is a hand-written deleter holding the
  bucket-admin credential on the storage host, doing what the lifecycle job
  already does. It stays the fallback if the job proves unreliable.
- **Lifecycle `Expiration` instead of the agents' prune.** It would move retention
  from each app's `backup:` block to one bucket-wide rule and lose the per-app
  retention ADR 0068 defines.
- **Leaving it as accepted residual risk.** The cloud copies cover the loss, but
  the first restore source would stay deletable by the host that wrote it.

## Assumptions

- **Claim:** the compose wiring works under Docker: the admin and worker start
  in the server's network namespace, reach its master and filer on localhost,
  and no container on `caddy-proxy` reaches the admin.
  **Breaks if wrong:** the worker cannot connect, so there is no lifecycle and no
  vacuum, or the admin needs a published port.
  **Checked by:** a Molecule scenario on the SeaweedFS target. The listener and
  reachability behaviour is checked in a bare namespace; `network_mode` itself
  and the pinned image under Docker are not.
- **Claim:** `docker-volume-backup`'s Go minio client uploads and prunes against
  a versioned bucket with a default retention as the Python SDK did, and the
  restore listing and `cloud_sync` work on the result.
  **Breaks if wrong:** a backup fails to upload, or a pruned archive still shows
  in a listing and is restored or relayed.
  **Checked by:** the `backup_agent` and `cloud_sync` Molecule scenarios run
  against a target created the way production will be.
- **Claim:** a stopped or failing worker is noticed before the disk fills.
  **Breaks if wrong:** lifecycle stops silently and the bucket grows.
  **Checked by:** naming the signal before approval, such as a check that fails
  when noncurrent versions older than the lock window plus two days exist, and
  testing that it fires with the worker stopped.
- **Claim:** the data volume has room for the retention window plus two days of
  the largest app's archives, with the rest of the host's use on top.
  **Breaks if wrong:** the disk fills, and a locked archive cannot be removed over
  S3 to make room.
  **Checked by:** the volume's free space against the largest app's archive size,
  before the conversion.

## Consequences

- The lock is an S3-layer control. The filer API and `weed shell` bypass it, so
  it holds against a holder of an S3 credential, not against a user of the filer
  UI behind Tinyauth or a compromised `storage` host, which the threat model
  leaves out of scope. Limiting the filer route to read methods would close the
  first of those and is not decided here.
- Compliance cannot be undone for an object that already has it. Lowering the
  default retention affects only later uploads. The relief for an archive that
  must go early is a delete through the filer by the operator.
- A compromised host can still write new objects, and while the window lasts it
  cannot remove them over S3. It can fill the volume with them. This is a
  denial of space on `storage`, which the operator clears through the filer.
- Writing a rogue newer archive is not addressed here; ADR 0079 covers it.
- The stack gains two long-lived processes and the vacuum schedule moves to the
  worker's job. A stopped worker means no lifecycle removal, while the master's
  sweep resumes.
- `amazon.aws` 11.5.0 has no lifecycle module. The rules need a collection that
  provides one or a direct API call.
- [`backup.md`](../../topics/disaster-recovery/backup.md) and
  [`backup-threat-model.md`](../../topics/disaster-recovery/backup-threat-model.md)
  describe the lock, and the accepted residual risk narrows, when this lands. The
  Molecule probe that asserts a plain delete leaves no marker changes with it.

## Invariants

- No S3 identity, including the bucket-admin identity, can remove or shorten an
  archive version before its lock ends.
- No backup identity holds an action that sets retention or bypasses it.
- An archive's data is removed only after it has been pruned and its lock has
  ended.
- The admin API of the SeaweedFS stack is not routed through Caddy.
- No app's retention is shorter than the lock window.

## Non-goals

- Archives written after a compromise, which ADR 0079 addresses.
- The filer API, `weed shell` and the `storage` host.
- The cloud copies, whose lock and lifecycle stay provider-native.
- Which retention the apps use. The window follows `backup_defaults` and is not
  chosen here.

## Validation

- Extend the `identity_scoping` scenario: a scoped identity's delete of a freshly
  written archive by `VersionId` is refused, and so is the bucket-admin
  identity's.
- A Molecule scenario drives the lifecycle job on demand through the admin API
  against a target with a short explicit retention, and asserts that an expired
  superseded version and an orphaned marker are removed and a locked one is not.
  A count-based rule stands in for the day count there, since a day cannot
  elapse in a test.
- A unit test over `backup_plan` fails when an app's retention is below the lock
  window.
- The operational signal for a stopped worker, once named.

## Reconsideration triggers

- The lifecycle job fails to remove superseded versions after an image upgrade.
  The timer is then the fallback.
- SeaweedFS enforces the lock at the filer layer.
- A backup identity is given an action that sets or bypasses retention.
- The largest app's archive grows past what the volume holds for the window plus
  two days.
