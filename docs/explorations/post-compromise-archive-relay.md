---
id: EXP-post-compromise-archive-relay
title: "How could the lab notice that an archive a compromised host made has been relayed offsite as if it were genuine?"
type: exploration
status: open
summary: "Whether a check between an app host's archive and its offsite copy can catch a tampered new archive, given that the host's own signing key cannot."
topic: backup-recovery
related: [ADR-0010, ADR-0079]
---

# How could the lab notice that an archive a compromised host made has been relayed offsite as if it were genuine?

[ADR 0010 (Offsite copy deletion)](../decisions/0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md)
keeps a landed object from being replaced or deleted, and the provider lock keeps
it for its window. Neither says anything about the next archive. A compromised
app host that writes tampered state under a new timestamp has produced a file the
relay copies like any other, and a restore that selects the newest archive reads
it. The question is what, if anything, stands between that archive and the
cloud copy a restore trusts when `storage` is gone.

## What bears on it

- The relay is `rclone copy --immutable` per (app, cloud target) pair, daily
  ([`cloud-sync.md`](../topics/disaster-recovery/cloud-sync.md)). It protects an
  object that has landed and judges nothing about a new one.
- A compromised app host can write its own SeaweedFS archives, because anything
  that produces a backup needs that write path
  ([`backup-threat-model.md`](../topics/disaster-recovery/backup-threat-model.md)).
- The freshness check compares the newest object's age with the app's cron
  period plus a buffer. It shows that some recent file exists, not what is in it
  ([`backup.md`](../topics/disaster-recovery/backup.md)).
- [ADR 0079 (Backup archive authenticity)](../decisions/0079-knowing-a-backup-archive-came-from-its-host/revision-000.md)
  and [`backup-archive-signing.md`](../projects/backup-archive-signing.md) sign
  each archive with a key held on its host. That separates an archive written by
  someone without the host from one written by the host, and it puts root on the
  host out of scope. An archive the compromised host made itself carries a valid
  signature.
- Older versions stay retained and restorable for the lock window (R2 29 days,
  B2 28, OCI 3), so a restore can go back to an archive from before the
  compromise if someone knows which one that is.
- What has to be found out: how much an archive's size and file count vary night
  to night for each app, and which of an app's contents are stable enough to
  assert on (the CA's root fingerprint, the count of accounts).

## Options

- **A relay delay.** `cloud_sync` offers an archive to the cloud only when it is
  a set number of days old, so a compromise noticed within that time never
  reaches the offsite copy. It costs an offsite copy that trails by the delay,
  which weakens the loss-of-`storage` case the copy exists for, and it needs a
  second source of the "noticed" signal to be worth anything.
- **A size and shape gate.** The relay holds back an archive whose size or entry
  count differs sharply from the previous one and alerts. It is cheap and has no
  new credential. A careful attacker keeps the size, and an app whose data
  legitimately jumps (a CA after many issuances) raises false alarms.
- **A canary restore.** A scheduled job restores the newest archive of selected
  apps into a scratch volume, never the live one, and asserts invariants the
  genuine data holds. It sees content, which the other two do not. It needs a
  decryption key held where the job runs, a list of invariants per app, and the
  scratch restore's own cost and failure modes, and it covers only the apps with
  an invariant written.
- **Leave it.** The failure needs a compromised app host and a restore from the
  newest archive without a second look. The lock window and retained versions
  already allow a restore from an earlier archive.

## Leaning

None yet. The delay and the gate are cheap to try but stop little alone; the
canary restore is the only one that reads content, and the apps it would cover
first are those whose restore the lab depends on most (`step-ca`, `lldap`,
`tinyauth`). What would change this is the measured size variation per app: if
it is small, the gate becomes worth running beside the others.
