---
id: ADR-0103
revision: 0
type: adr
title: Where Tofu's state is held
short: Tofu state backend
solution: An encrypted state bucket in the R2 account the lab already uses, with a credential of its own, and a write-only GPG copy of each apply's state in the B2 account
summary: Where OpenTofu's state lives so that the record of what Tofu built depends on neither one machine nor a machine Tofu builds.
topic: deployment-platform
status: superseded
superseded_by: 1
related: [ADR-0111, ADR-0048, ADR-0058, ADR-0102]
relies_on:
  - adr: ADR-0058
    reason: "It rules out the operator host as the backend because that host can be built by Tofu, which presupposes the operator host as ADR 0058 describes it."
---

# 0103. Where Tofu's state is held

## Problem

Tofu's record of what it built is a local file on one VM. Losing that VM loses the record,
and every rebuild changes it. What has to be true: the state survives the loss of the
host that runs Tofu and of any host Tofu builds, only the operator can read it, and
recovering it needs nothing that Tofu itself has to rebuild first.

## Decision

State lives in a bucket named `opentofu-state` on R2, made by hand like the snapshot
buckets. A second bucket on B2 (a different name if that one is taken, since B2 names
are global) holds copies.

- **Live backend.** R2. OpenTofu's `s3` backend points at the bucket with a credential
  that reads, writes and deletes in that bucket and nothing else. It lives in the credentials file ADR 0048 describes, and a
  script beside the snapshot ones in `tools/cloud_credentials/` mints it and does not
  cache it. It is rotated on the cadence of the snapshot write leaf.
- **Copy.** After each apply the guarded wrapper
  ([ADR 0102](../0102-knowing-what-a-tofu-change-will-do/revision-000.md)) pushes
  `tofu state pull` output to B2 under a new key each time, encrypted to the backup GPG
  public key as `snapshot-push.sh` does, with a write leaf that cannot delete. The copies
  are the history R2 does not keep, the way back from a bad state write, and the recovery
  path if the R2 account is lost. They accumulate at a few megabytes each; pruning is a
  lifecycle rule set on the bucket by hand.
- **Encryption.** OpenTofu state encryption, so the provider holds only ciphertext and a
  plan file is covered too. The key is in the credentials file and has an offline copy
  held like the backup GPG key, since the file is what a total loss removes.
- **Locking.** The backend's native lock file (`use_lockfile`), which R2 enforces.
- **Migration.** `tofu init -migrate-state` from the operator host. The local file and
  its copies are deleted once a plan against the bucket shows no change.

```mermaid
flowchart LR
    OP["Operator host<br/>runs Tofu"] -->|"read, lock, write, delete<br/>encrypted state"| LIVE["Live bucket<br/>R2"]
    OP -->|"after each apply<br/>GPG copy, no delete"| COPY["Copy bucket<br/>B2"]
    KEY["Offline: GPG key,<br/>state encryption key"] -.->|"recovery only"| OP
```

## Invariants

- No host that Tofu builds holds or is needed to reach the state.
- A provider never holds readable state.
- The R2 credential reaches the state bucket only, and the B2 copy credential cannot
  delete.
- After migration the operator host's file is not the only copy.

## Non-goals

- Access to the state from the CD agent, or applying from it
  ([ADR 0102](../0102-knowing-what-a-tofu-change-will-do/revision-000.md)).
- More than one workspace, or a second maintainer's access.
- Rotating the state encryption key on a schedule.

## Reconsideration triggers

R2 drops conditional writes or ends its free allowance; B2 gains conditional writes and
a single provider with history becomes simpler; a second maintainer or
the CD agent needs to read the state; the operator host becomes something Tofu cannot
rebuild by design; spare hardware outside the node makes a local backend worth running.
