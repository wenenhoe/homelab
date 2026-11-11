---
id: EXP-second-cloud-archive-window
title: "Can a second cloud hold the game-world archive for a short window of its own?"
type: exploration
status: open
summary: "How a second cloud can hold the game-world archive for a short window without changing the retention of the other apps' archives already there."
topic: backup-recovery
related: [ADR-0006, ADR-0010, ADR-0068]
---

# Can a second cloud hold the game-world archive for a short window of its own?

The game-world archive is held by one cloud besides SeaweedFS. A copy at a
second provider would survive the loss of either of the other two, but the
archive needs a much shorter window than the other apps' archives, and what
holds those is a retention that applies to the whole bucket. A second cloud can
take the archive only if its window can differ without weakening the retention
of anything else stored there.

## What bears on it

- Every backed-up app except the game world is relayed to R2 and B2; the game
  world alone is relayed to OCI
  ([`cloud-sync.md`](../topics/disaster-recovery/cloud-sync.md#targets)).
- R2 and B2 each apply one lock and one delete-after to every object in their
  bucket. A world archive sent there would stay about a month, many times the
  window that suits it and past the provider's free storage allowance.
- A rule for one prefix does not fit the existing buckets. On R2,
  [lock rules without a prefix apply to every object, and the longest retention
  wins where rules overlap](https://developers.cloudflare.com/r2/buckets/bucket-locks/),
  so the bucket-wide rules would override a shorter one and would first have to
  be re-scoped to each other app's prefix. On B2,
  [the default bucket retention applies to every prefix](https://www.backblaze.com/docs/cloud-storage-configure-immutable-storage-for-reseller-and-msp-customers),
  so a different retention needs a separate bucket or retention set per object.
- A target is a name with its own bucket and credentials.
  `cloud_sync_targets` (`host_vars/storage.yaml`) maps a name to a bucket, an
  endpoint and write credentials; a job is one (app, target) pair; restore
  discovery reads the same names with read credentials; an app lists its
  targets in `backup.cloud_targets`
  ([ADR 0068](../decisions/0068-where-per-app-backup-settings-get-their-defaults/revision-000.md)).
  A second bucket on a provider would be a second target name.
- A dedicated bucket on R2 and B2 has precedent: the secrets-store snapshots use
  their own bucket on each, and the leaf-key functions take the bucket as an
  argument that defaults to the relay's own.
- R2 and B2 hold about 50 MB today, a small fraction of either free allowance.
- Lock and lifecycle rules are provider-native console settings, not managed by
  the repo
  ([ADR 0010](../decisions/0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md)),
  so a new bucket's rules are made by hand and recorded in `cloud-sync.md`. A
  relay's credentials are kept to one blast radius per provider
  ([ADR 0006](../decisions/0006-offsite-backup-credential-blast-radius/revision-000.md)).
- The relay's transfer cap ([`cloud-sync.md`](../topics/disaster-recovery/cloud-sync.md#transfer-cap))
  bounds what a bucket can hold at the cap times the days its objects are kept.
  For a world-archive target that holds objects d days, a cap near one archive
  (about 2 GB) fits a 10 GB allowance up to d = 5, and a cap that also carries a
  missed day (two archives, about 3.6 GB) fits only d = 2.
- Constraints any answer must keep: the relay stays additive (`rclone copy
  --immutable`, never `sync`); an archive is offered to a cloud before
  SeaweedFS prunes it; a new bucket or rule never shortens the lock or
  delete-after of an archive already in an existing bucket; a lock on a new
  bucket stays strictly below that bucket's delete-after.

## Options

1. **A dedicated bucket per provider**, with its own lock and lifecycle rules for
   the short window and one new target name per provider. It needs the bucket
   created by hand in each console, a write and a read credential scoped to it,
   entries in `cloud_sync_targets` and in the restore-discovery read
   credentials, and updates to `cloud-sync.md` and `scoping.md`.
2. **Retention set per object on B2.** The shared bucket keeps its default and
   the world archive carries a shorter retention set at upload. R2 cannot do
   this and would still need option 1. It needs a way for the relay to set
   retention for one app and a credential allowed to write retention.
3. **One cloud, as today.** SeaweedFS and OCI hold two copies.

Whichever of 1 or 2 is chosen leaves a second question: which archives each
provider receives. One answer divides the window by age. The newest archives go
to R2 and B2 as they land and expire there after a few days under their own
short rules; OCI receives an archive only once it is older than that band and
keeps it until the window ends. The relay would select by age with rclone's
`--max-age` on the R2 and B2 jobs and `--min-age` on the OCI job. With
SeaweedFS keeping seven days and the boundary at k days, R2 holds about k
archives, B2 about one more and OCI the other seven minus k. At the archive's
size when this was written, about 1.8 GB, a boundary of 2 days leaves OCI near
9 GB, and 3 days leaves every provider near 7 GB or less.

The cap decides how long a short window can be: the days an object is kept,
times the cap, must stay under the allowance. At k = 3, R2 keeps objects about 3
days, B2 about 4 and OCI 5, so caps of about 3 GB, 2.5 GB and 2 GB hold each to
10 GB or less (9, 10 and 10). Each is under two archives, so a missed day is
carried by running the relay by hand. rclone sizes in `G` are binary, so the
values are set a little below these, and every cap has to rise with the
archive, which shortens the window it can afford.

Options that lost, with the reason:

- **Prefix rules in the existing R2 and B2 buckets.** The longest retention wins
  on R2 and the default applies to every prefix on B2, so a shorter rule would be
  overridden or ignored.
- **Every provider receives every archive.** Each would hold the whole seven-day
  window, past each free storage allowance.
- **A longer window on OCI alone.** No second provider, and storage above the
  free allowance is billed.
- **OCI's cooler tiers for older archives.** Their minimum storage periods of 31
  and 90 days exceed the window, so each archive is billed for the whole minimum.

## What has to be checked first

- Whether a second cloud copy is wanted at all, given two copies already exist.
  That is the maintainer's call on how many independent copies the world needs.
- That the largest share of the window one provider holds stays inside its free
  allowance as the archive grows; the age boundary can move.
- That `--min-age` and `--max-age` select by the time SeaweedFS reports, which is
  upload time, using the SeaweedFS test target the Molecule scenarios use.
- That restore discovery finds an archive only some of an app's targets hold, and
  can read a target whose credentials are not the provider's existing pair.
- That the credential tooling can make a write and a read credential for a second
  bucket per provider with the bucket argument its key functions already take.

## Leaning

None.
