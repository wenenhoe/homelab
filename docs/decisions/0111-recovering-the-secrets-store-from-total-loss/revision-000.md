---
id: ADR-0111
revision: 0
type: adr
title: Recovering the secrets store from total loss
short: Secrets store recovery
solution: Keep only the Shamir shares and a scoped read-only snapshot credential outside OpenBao, and push its encrypted snapshot straight from its own host to two cloud providers
summary: OpenBao can be rebuilt from nothing, so nothing needed to fetch its own backup lives only inside it, and the snapshot reaches the offsite copy without the app-backup pipeline.
topic: secrets-store
status: accepted
related: [ADR-0006, ADR-0010, ADR-0013, ADR-0018]
former_ids: [ADR-0017, ADR-0019]
---

# 0111. Recovering the secrets store from total loss

## Problem

If every credential, including the ones needed to fetch and restore OpenBao's own backup, lives only
inside OpenBao, a sealed or lost instance cannot be brought back: nothing exists yet to authenticate
to cloud storage and pull the snapshot that would unseal it. What has to be true: OpenBao can be
rebuilt from what survives outside the `security` host, and the encrypted snapshot it is rebuilt from
reaches the offsite copy without widening who can touch the recovery path.

## Context

**Threat model.** The scenario is total loss of the `security` host: disk failure, a rebuild, or a
compromise that needs a clean rebuild. Recovery then depends entirely on what survives outside that
host. This differs from
[ADR 0006](../0006-offsite-backup-credential-blast-radius/revision-000.md), where a compromised app
host reaches the offsite backup: here the thing restored is the credential store itself, so nothing
kept only inside it can be part of its own recovery. A second adversary is a compromised `storage`
host, the one
[ADR 0010](../0010-preventing-homelab-side-deletion-of-offsite-copies/revision-000.md) and ADR 0006
already reason about for every other app's backup. The assets are the `openbao-snapshots` write leaf
and the guarantee that a started push completes.

Every other app's offsite backup goes through `backup_agent` (tar the volume, encrypt, land on
SeaweedFS) and `cloud_sync` (relay SeaweedFS onward on its own timer). `backup_agent`'s job, tarring a
volume, does not fit OpenBao, since stopping it to tar its data volume seals it and needs a manual
unseal on every cycle
([ADR 0018](../0018-unsealing-the-secrets-store-after-restart/revision-001.md)). The open question was
narrower: whether the encrypted raft snapshot should be pushed directly or land on SeaweedFS for
`cloud_sync` to relay, which would reuse its scheduling. Relaying would give `storage` the encrypted
blob at rest and require the write leaf to live on `storage`. GPG's integrity protection means a
compromised `storage` still could not read or usefully alter the ciphertext. The risk is a second
host holding standing access to a recovery-critical credential, plus a new silent failure: a
misbehaving relay could delay or drop the push before it reaches the cloud, which a direct push, run
in front of the operator, does not have.

## Decision

- **Two classes of secret.**
  - *Recovery-critical*, which must exist before OpenBao does, is exactly two categories: the Shamir
    unseal key shares, and a narrowly scoped **read-only** cloud credential limited to OpenBao's own
    snapshot bucket and prefix, one per replica provider. Both live outside OpenBao permanently, with
    the offline handling the repository already gives its GPG private key: a password manager plus one
    offline copy, never committed, never only on a host.
  - *Operational* is everything else: day-to-day cloud credentials, app secrets, everything the secret
    catalog drives. These can live only in OpenBao once it is up.
- **Restore order.** Offline break-glass bundle, then a bare host with OpenBao installed, then fetch
  the raft snapshot with the scoped read-only key, then restore the snapshot and unseal, then Ansible
  authenticates through AppRole, then the restore playbook pulls everything else from OpenBao.
- **The snapshot is pushed directly.** `snapshot-push.sh` pushes from `security` to R2 and B2 with
  `rclone copy`, in the same run as the snapshot save and GPG encryption. It never touches SeaweedFS or
  `cloud_sync`, and `storage` has no role in OpenBao's backup. The write leaf
  (`create_snapshot_write_keys.py`) is minted and cached only on `security`.
- **Two providers, one bucket name.** The read-only credential is built for R2 and B2, both using a
  bucket named `openbao-snapshots`, so recovery does not depend on one cloud vendor being reachable. It
  is minted by `create_snapshot_readonly_keys.py`, outside the rotation machinery it cannot depend on,
  and printed once, not cached.

## Alternatives considered

- **Everything in OpenBao, with cloud auto-unseal as the escape hatch.** The KMS credential that enables
  it has the same chicken-and-egg problem one level up, adds a second offline secret, and makes every
  boot depend on a cloud provider. Rejected here; the choice between Shamir and auto-unseal stays with
  the unseal decision.
- **Keep the file-based cache as a permanent fallback beside OpenBao.** It leaves two authoritative
  sources for the same secrets, the drift a secrets manager exists to remove.
- **Relay the snapshot through SeaweedFS and `cloud_sync`.** Cheaper scheduling, but it hands `storage`
  the blob and a credential able to relay it, and adds a silent-failure mode.

## Consequences

- The read-only snapshot credential is a new category for `tools/cloud_credentials/`: narrower than any
  leaf credential, bucket and prefix limited, and provisioned outside the rotation machinery.
- The operator's break-glass process gains the Shamir shares beside the GPG key, and a second narrowly
  scoped credential outside any automated rotation. Both are one-time, human-attended items.
- Compromising `storage` yields nothing toward this recovery path. This is the per-host containment of
  ADR 0006, reached by never granting the credential at all and not by scoping it once granted.
- No shared scheduling. `controller`'s AppRole gives a credential safe to leave on disk for an
  unattended job, but `controller` is the operator's own machine and runs nothing on a schedule, so the
  push runs by hand until a dedicated automation host exists. Then the natural step is a timer on
  `security`, the shape `cloud_sync` already is, and not an integration with the existing pipeline.
- Proving the backup and restore loop before any secret's authoritative copy moves into OpenBao is the
  actual test of this split, as described in
  [`openbao-backup-restore.md`](../../topics/secrets/openbao-backup-restore.md). Setup is in
  [`openbao.md`](../../topics/secrets/openbao.md).

## Invariants

- Nothing needed to fetch and restore OpenBao's snapshot is stored only inside OpenBao.
- The recovery-critical set is the Shamir shares and the scoped read-only snapshot credentials, and
  nothing else.
- The snapshot write leaf exists only on `security`, and `storage` holds no copy of the snapshot or a
  credential for it.
- A failed push fails in front of the operator who started it.

## Non-goals

- Choosing between Shamir and auto-unseal
  ([ADR 0018](../0018-unsealing-the-secrets-store-after-restart/revision-001.md)).
- Offsite backups of other apps' volumes, which go through `backup_agent` and `cloud_sync`.
- Running the push unattended, which waits on a dedicated automation host.

## Reconsideration triggers

- A dedicated automation host exists, so the push can run on a timer.
- A cloud KMS or another auto-unseal path is adopted, changing what must exist before OpenBao.
- A provider can no longer give a read-only credential limited to one bucket and prefix.
