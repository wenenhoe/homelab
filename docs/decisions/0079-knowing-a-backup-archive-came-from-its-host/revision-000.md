---
id: ADR-0079
revision: 0
type: adr
title: Knowing a backup archive came from its host
short: Backup archive authenticity
solution: A detached signature per archive from a per-host key, checked at restore against public keys pinned in the repository
summary: How a restore shows that the archive it is about to apply was written by the host it claims to be from, whoever else can write to the places archives are kept.
topic: backup-recovery
status: working
related: [ADR-0006, ADR-0010, ADR-0012]
---

# 0079. Knowing a backup archive came from its host

## Problem

A restore applies an archive to a host's volumes. The archive is encrypted to
a public key and found by name. Neither says who wrote it: the key is on every
backup host and in the repository, and a name is typed by whoever uploads the
object.

What has to be true: a restore applies an archive only if it is shown to have
been written for that host by something holding that host's key, and an object
that lacks that proof is refused and reported, not skipped for an older one.

## Context

Archives pass through three places before a restore reads them
([`backup.md`](../../topics/disaster-recovery/backup.md),
[`cloud-sync.md`](../../topics/disaster-recovery/cloud-sync.md)):

- Each app host's `backup_agent` uploads to its own prefix on SeaweedFS with an
  identity scoped to that prefix.
- `cloud_sync` on `storage` copies those objects, with `rclone copy`, to R2, B2
  and OCI.
- `ansible/scripts/restore_all.py` lists SeaweedFS first and then each cloud
  target, picks the object with the newest timestamp in its name, downloads it
  and decrypts it with the private key on the controller. A single-app restore
  runs the same way through `restore.yaml`.

Decrypting shows only that the file was encrypted to the backup public key,
which is published. The timestamp is part of the file name. The restore
therefore trusts whatever sits under the prefix, and the cloud copy is the one
read when `storage` is gone.

[`backup-threat-model.md`](../../topics/disaster-recovery/backup-threat-model.md)
bounds a compromised app host to its own archives and leaves a compromised
`storage` host and a network attacker out of scope. A restore reads the cloud
copy in the case where `storage` is the host that was lost, and a cloud account
credential is a different thing from a host.

**Threat model.** The adversary has a write path to a place archives are kept,
a SeaweedFS or cloud credential, the relay on `storage`, or the provider's
account, and does not hold a host's signing key or root on that host. The asset
is the state a restore writes: the volumes of `step-ca`, `lldap`, `tinyauth` and
the rest, which hold the lab's CA, accounts and sessions. The attack path is an
object named with a newer timestamp than the genuine ones, encrypted to the
public key; the next restore selects it, decrypts it and applies it. Out of
scope: root on the host that signs, which can sign anything its agent could
back up (the threat model's accepted residual risk), and deleting the newest
genuine archives so that an older, genuine one is restored.

OpenSSH signatures suit this because every backup host and the controller
already have `ssh-keygen`. Checked with OpenSSH 9.6 on a throwaway key pair:

- A signature made with `ssh-keygen -Y sign -n homelab-backup` verifies against
  an `allowed_signers` line for the same principal and fails for another
  principal's key, for the archive altered by one byte, for another namespace,
  for a key that is not listed and for a missing signature file.
- A listed key can carry `valid-before=`, and `-Overify-time=` makes a
  retired key verify only for what it signed before its cutoff.

## Decision

- **One key per host.** Each `backup_agent` host has an Ed25519 signing key,
  generated on that host, readable by root only and never mounted into the agent
  container. It signs for the host's own archives only.
- **A detached signature beside each archive.** A host-side unit signs each
  archive with `ssh-keygen -Y sign -n homelab-backup` and uploads
  `<archive name>.sig` to the same prefix, through the host's own SeaweedFS
  identity. `cloud_sync` relays it with the archive.
- **Pinned public keys.** An `allowed_signers` file in the repository holds one
  line per host, with the host name as the principal. A new or replaced key is a
  reviewed diff. The restore reads the file from the checkout it runs from, never
  from the place it fetches archives.
- **Verify before use.** A restore verifies the archive's signature against the
  principal for the host in its manifest entry before it decrypts or applies
  anything. Candidates for "newest" are only objects that have a `.sig`; `.sig`
  objects are never themselves candidates.
- **Refuse, don't fall back.** If the newest object fails verification, the
  restore stops, names the object and why, and applies nothing. An operator can
  name an older archive on purpose; the restore never chooses one silently.
- **Rotation.** A replaced or rebuilt host gets a new key and a new line. The old
  line stays, with `valid-before` set to the replacement time, and the restore
  verifies at the signature time the archive's name carries, so archives signed
  by the retired key still verify.

## Alternatives considered

- **One shared signing key.** Simpler to pin and rotate, and a compromise of any
  one host then forges every host's archives. Per-host keys keep that to the
  compromised host.
- **Sign with the backup GPG key.** Its private half stays offline and is on no
  host by design, so it cannot sign online. A second GPG keyring per host would
  need an agent and expiry handling on every host that `ssh-keygen` does not.
- **A hash manifest committed to the repository.** One commit per backup per
  app, nightly, and a pin that moves faster than a reviewer can look.
- **Rely on object versioning or object lock.** They protect an existing object
  from overwrite or delete, which [ADR 0010](../0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md)
  covers, and not a new object inserted beside it.
- **Authenticated encryption with a per-host symmetric key.** It proves the
  writer, and every host would then hold a key that decrypts its backups, which
  the offline private key exists to prevent.

## Assumptions

- **Claim:** the host-side unit can sign exactly the bytes the agent uploaded,
  without a second copy of every archive on the host and without giving the agent
  container the key.
  **Breaks if wrong:** the signature covers something other than the uploaded
  object, so a genuine archive fails verification, or the key ends up readable
  from the container and the signature proves nothing.
  **Checked by:** a spike on one host: sign from the object the host's own
  identity downloads after the upload, compare it with the agent's output, and
  confirm the container cannot read the key.
- **Claim:** `cloud_sync` copies `.sig` objects with their archives under every
  target's retention, so a signature is never expired before its archive.
  **Breaks if wrong:** a restore from the cloud copy finds archives with no
  signature and refuses all of them.
  **Checked by:** reading `cloud_sync`'s command and each target's lifecycle
  rule, and a Molecule scenario that relays an archive and its signature.
- **Claim:** a signature arrives shortly after its archive, so a restore that
  finds an archive with no `.sig` yet is looking at a run in progress and not a
  failure.
  **Breaks if wrong:** the hourly freshness check ([ADR 0012](../0012-verifying-backups-actually-land/revision-000.md))
  reports unsigned archives as missing, or a restore refuses the latest good one.
  **Checked by:** measuring the lag on one host, and extending the freshness check
  to alert on an archive left unsigned past a set time.

## Consequences

- Every archive gains a second object, and a new unit on each backup host.
- The signing key is a new secret on each host. It is root-only, and a root
  compromise of that host yields signed forgeries for that host's own apps, which
  is the residual risk the threat model already accepts.
- A restore of a host whose key was never pinned refuses until the key is
  pinned. First deploy of a host adds a step: its public key goes into
  `allowed_signers` through a pull request.
- Archives made before this lands have no signature. The restore needs an
  explicit, logged override for them until the retention window has passed.
- [`backup-threat-model.md`](../../topics/disaster-recovery/backup-threat-model.md),
  [`backup.md`](../../topics/disaster-recovery/backup.md) and
  [`restore.md`](../../topics/disaster-recovery/restore.md) describe the signing
  and the refusal when it lands.

## Invariants

- A restore never decrypts or applies an object whose signature does not verify
  against the pinned key for its host.
- No signing key is in the agent container, in the repository or off its host.
- `allowed_signers` changes only through a reviewed diff, and the restore never
  reads it from the archive store.
- A failed verification stops the restore. It never selects an older archive.

## Non-goals

- Rollback to an older genuine archive by deleting newer ones.
- Confidentiality of archives, which the GPG encryption provides.
- The OpenBao raft snapshot, which is restored by hand from the operator's own
  copy ([`openbao-backup-restore.md`](../../topics/secrets/openbao-backup-restore.md)).

## Validation

- Unit tests for the restore's selection and verification: a valid signature
  passes; an altered archive, a signature by another host's key, an unlisted key,
  another namespace and a missing `.sig` each refuse; a newest object that fails
  does not fall through to the previous one; `.sig` objects are never picked as
  the archive.
- A Molecule scenario with two fake hosts: each signs, and the controller
  verifies each and refuses the other's archive filed under the wrong prefix.
- A test that fails when an app host has a backup schedule and no line in
  `allowed_signers`.

## Reconsideration triggers

- A host other than `storage` is given a path to write another host's prefix.
- A backup host's key is suspected exposed. Replace it, and treat its archives
  since the exposure as unverified.
- `docker-volume-backup` gains signing of its own.
