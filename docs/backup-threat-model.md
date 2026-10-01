# Backup Threat Model

The backup design assumes one adversary: a compromised app host (`services`, `security`, or `play`). A compromised `storage` host and a network-level attacker are out of scope. The asset is the offsite copy, which exists to survive the loss of the host it protects — so a credential that host holds is exactly as dangerous as the access it grants. Every app host's `backup_agent` holds a live, write-capable S3 credential by necessity, which makes that credential's reach the thing to bound.

The reasoning and the alternatives considered are in [ADR 0006](decisions/0006-offsite-backup-credential-blast-radius/revision-000.md) (credential scope) and [ADR 0010](decisions/0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md) (deletion propagation). This page states what holds today. The mechanism itself is in [`backup.md`](backup.md) and [`cloud-sync.md`](cloud-sync.md).

## Constraints

- **Cloud credentials never touch an app host.** R2/B2/OCI write access exists only on `storage` (`cloud_sync`), so compromising `services`, `security`, or `play` yields no cloud credential.
- **Each app host's SeaweedFS identity is scoped to its own prefix only.** The identities are defined in `docker/seaweedfs/configs/s3-identity.json.j2` and listed under [Storage host](backup.md#storage-host).

Compromising one app host therefore caps the damage at that host's own SeaweedFS archives.

## Accepted residual risk

A compromised app host can still tamper with its own SeaweedFS archives: whatever produces a backup needs some write path to stage it, and that path is equally available to whatever is compromised on the host.

## Why the cloud copy holds

`cloud_sync` relays with rclone `copy`, never `sync`, so nothing on-prem, even fully compromised, can delete or overwrite what has already landed in the cloud. A compromised app host tampering with its own SeaweedFS archives can't propagate that tampering to the cloud copy for the same reason. Setup, per-provider retention and the sync mechanism are in [`cloud-sync.md`](cloud-sync.md).

## Automated coverage

`ansible/roles/seaweedfs_bucket/molecule/identity_scoping` renders the real `s3-identity.json.j2` against a live throwaway SeaweedFS target with two fake backup hosts, and asserts that cross-prefix write and read are denied and that Admin actions aren't available to a scoped identity.

The write-denial assertion matches the `AccessDenied` substring, confirmed against a real SeaweedFS error (`An error occurred (AccessDenied) when calling the PutObject operation: Access Denied.`). The read-denial and Admin-action assertions use the same substring match but haven't been checked against real output; if one proves fragile, that is the assertion to revisit.
