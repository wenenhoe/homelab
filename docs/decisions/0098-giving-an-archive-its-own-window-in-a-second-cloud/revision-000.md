---
id: ADR-0098
revision: 0
type: adr
title: Giving an archive its own window in a second cloud
short: Second cloud copy, own window
solution: 'Undecided: a dedicated bucket per provider, retention set per object on B2, or one cloud copy as today'
summary: How a second cloud can hold the game-world archive for a short window of its own without changing the retention of the other apps' archives already there.
topic: backup-recovery
status: working
related: [ADR-0006, ADR-0010, ADR-0068]
---

# 0098. Giving an archive its own window in a second cloud

## Problem

The game-world archive is held by one cloud besides SeaweedFS. A copy at a
second provider would survive the loss of either of the other two, but the
archive needs a much shorter window than the other apps' archives, and what
holds those is a retention that applies to the whole bucket. A second cloud
can take the archive only if its window can differ without weakening the
retention of anything else stored there.

## Context

- Every backed-up app except minecraft is relayed to R2 and B2; minecraft
  alone is relayed to OCI
  ([`cloud-sync.md`](../../topics/disaster-recovery/cloud-sync.md#targets)).
- R2 and B2 each apply one lock and one delete-after to every object in their
  bucket (table in `cloud-sync.md`). The relay copies each archive once, so a
  world archive sent there would stay for about a month: many times the window
  that suits it, and well past the provider's free storage allowance.
- A rule for one prefix does not fit the existing buckets. On R2,
  [lock rules without a prefix apply to every object, and where rules overlap
  the longest retention wins](https://developers.cloudflare.com/r2/buckets/bucket-locks/),
  so the bucket-wide rules would override a shorter one; they would have to be
  re-scoped to each other app's prefix first, and a new app would then have no
  lock until its rule was added. On B2,
  [the default bucket retention applies to every prefix](https://www.backblaze.com/docs/cloud-storage-configure-immutable-storage-for-reseller-and-msp-customers),
  so a different retention needs a separate bucket or retention set on each
  object.
- A target is a name with its own bucket and credentials. `cloud_sync_targets`
  (`host_vars/storage.yaml`) maps a name to a bucket, an endpoint and write
  credentials; a job is one (app, target) pair; restore discovery reads the same
  names with read credentials from `restore_discovery_cloud_read_credentials`;
  an app lists its targets in `backup.cloud_targets`
  ([ADR 0068 (Backup defaults)](../0068-where-per-app-backup-settings-get-their-defaults/revision-000.md)).
  A second bucket on a provider would be a second target name.
- A dedicated bucket on R2 and B2 has precedent: OpenBao's snapshots use their
  own bucket on each (`tools/cloud_credentials/create_snapshot_write_keys.py`
  and `create_snapshot_readonly_keys.py`), and the R2 and B2 leaf-key functions
  take the bucket as an argument that defaults to the relay's own. The relay's
  leaf credentials are scoped to one bucket per provider, named by a constant
  in `tools/cloud_credentials/leaf_keys/`.
- R2 and B2 hold little today: the other apps' archives and the secrets-store
  snapshots come to about 50 MB in use, a small fraction of either provider's
  free storage allowance.
- Lock and lifecycle rules are provider-native console settings, not managed by
  the repo
  ([ADR 0010 (Offsite copy deletion)](../0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md)),
  so a new bucket's rules are made by hand and recorded in `cloud-sync.md`.
- The credentials a relay holds are kept to one blast radius per provider
  ([ADR 0006 (Offsite backup credentials)](../0006-offsite-backup-credential-blast-radius/revision-000.md)).

## Decision

Not yet. The candidates below answer the problem; none is chosen.

1. **A dedicated bucket per provider.** Its own lock and lifecycle rules set for
   the short window, and one new target name per provider that the app lists in
   `backup.cloud_targets`. It needs the bucket created by hand in each console,
   a write and a read credential scoped to it, entries in
   `cloud_sync_targets` and in the restore-discovery read credentials, and
   updates to `cloud-sync.md` and `scoping.md`.
2. **Retention set per object on B2.** The shared B2 bucket keeps its default
   and the world archive carries a shorter retention of its own, set when it is
   uploaded. R2 cannot do this, so it would still need candidate 1. It needs a
   way for the relay to set retention for one app only and a credential that is
   allowed to write retention.
3. **One cloud, as today.** SeaweedFS and OCI hold two copies of the archive.

Whichever of 1 or 2 is chosen leaves a second question open: which archives
each provider receives. One answer divides the window by age. The newest
archives go to R2 and B2 as soon as they land in SeaweedFS and expire there
after a few days under their own short rules. OCI receives an archive only once
it is older than that band, and keeps it until the window ends. The relay would
select by age with rclone's `--max-age` on the R2 and B2 jobs and `--min-age` on
the OCI job; the job manifest carries neither today.

With SeaweedFS keeping seven days and the boundary at k days, R2 holds about k
archives, B2 about one more (it hides a file before deleting it) and OCI the
other seven minus k. The newest k archives are then at two providers and the
older ones at one. At the archive's size when this was written, about 1.8 GB, a
boundary of 2 days leaves OCI near 9 GB and one of 3 days leaves every provider
near 7 GB or less, against the free allowance described in
[OCI window](../../topics/disaster-recovery/cloud-sync.md#oci-window).

## Alternatives considered

- **Prefix rules in the existing R2 and B2 buckets.** The longest retention
  wins on R2 and the default applies to every prefix on B2, so the existing
  rules would override or ignore a shorter one.
- **Every provider receives every archive.** Each would hold the whole seven-day
  window, which at the archive's current size is past each provider's free
  storage allowance.
- **A longer window on OCI alone.** It adds no second provider, and storage above
  the free allowance is billed.
- **Moving older archives to OCI's cooler tiers.** The Infrequent Access and
  Archive tiers have [minimum storage periods](https://docs.oracle.com/en-us/iaas/Content/Archive/Concepts/archivestorageoverview.htm)
  of 31 and 90 days, longer than the window, so each archive is billed for the
  whole minimum.

## Assumptions

- **Claim:** A second cloud copy is wanted: SeaweedFS and OCI already hold two
  copies of the archive.
  **Breaks if wrong:** The bucket, its credentials and its console rules are
  upkeep for no gain.
  **Checked by:** The maintainer deciding how many independent copies the world
  needs.
- **Claim:** The largest share of the window that one provider holds stays inside
  its free storage allowance as the archive grows.
  **Breaks if wrong:** That share is billed for the excess.
  **Checked by:** Reading each account's stored size after the first full window;
  the boundary between the age bands can be moved.
- **Claim:** rclone's `--min-age` and `--max-age` select objects by the time
  SeaweedFS reports for them, which is when they were uploaded.
  **Breaks if wrong:** An archive is copied to the wrong provider, or twice.
  **Checked by:** A spike against the SeaweedFS test target the Molecule
  scenarios use.
- **Claim:** Restore discovery finds an archive that only some of an app's
  targets hold, because it lists every target in the plan.
  **Breaks if wrong:** A restore reads the wrong provider or reports the archive
  missing.
  **Checked by:** Reading `restore_discovery` and its tests.
- **Claim:** The credential tooling can create a write and a read credential for
  a second bucket per provider with the bucket argument its key functions already
  take, and restore discovery can read a target whose credentials are not the
  provider's existing pair.
  **Breaks if wrong:** The change reaches further into the credential tooling
  than adding a target.
  **Checked by:** Reading the code, or a spike against a scratch bucket.

## Consequences

None yet: nothing is decided or built against this record. What exists is
described in [`cloud-sync.md`](../../topics/disaster-recovery/cloud-sync.md).

## Invariants

- The relay stays additive: `rclone copy --immutable`, never `sync`
  ([ADR 0010 (Offsite copy deletion)](../0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md)).
- An archive is offered to a cloud before SeaweedFS prunes it, so a provider
  that missed it does not leave it with no offsite copy.
- A new bucket or rule never shortens the lock or delete-after of an archive
  already in a provider's existing bucket.
- A lock on a new bucket stays strictly below that bucket's delete-after, as
  `cloud-sync.md` describes.

## Non-goals

- Making the archive smaller.
- Changing how long SeaweedFS keeps its copy, or the other apps' windows.
