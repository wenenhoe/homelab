# 0019. OpenBao snapshot push stays standalone, not routed through `backup_agent`/`cloud_sync`

**Status:** Accepted

## Context

Proving OpenBao's backup/restore loop needed a way to get the
encrypted raft snapshot
(`docs/openbao-backup-restore.md`) from `security` to R2/B2. Every
other app's offsite backup goes through `backup_agent` (tar the volume,
encrypt, land on SeaweedFS) and `cloud_sync` (relay SeaweedFS onward on
its own timer) — routing this through the same pipeline instead of a
standalone script was a real alternative, not a hypothetical one, and
would have bought scheduling for free.

`backup_agent`'s actual job is tarring a volume, and that doesn't fit
here regardless of the pipeline question: `docs/openbao.md` already
established that stopping OpenBao to tar its data volume means sealing
it, needing a manual unseal ([0018](0018-manual-shamir-unseal.md)) on
every cycle. So `backup_agent` itself was never in scope. The open
question was narrower: once `bao operator raft snapshot save` produces
the encrypted file, should the *push* to R2/B2 happen directly, or
should the file land on SeaweedFS and let `cloud_sync`'s existing timer
relay it — reusing the scheduling mechanism the rest of the fleet
already has?

**Threat model.** The adversary this decision considers is a
compromised `storage` host — the same host [0010](0010-cloud-sync-copy-not-sync.md)
and [0006](0006-backup-credential-blast-radius-threat-model.md) already
reason about for every other app's backup, but a new participant for
*this* one. The asset is the `openbao-snapshots` write leaf and the
guarantee that a triggered push actually completes. Today, `storage`
has zero role in OpenBao's backup pipeline: no data, no credential, no
transient copy. Routing through `cloud_sync` would end that — `storage`
would hold the encrypted blob at rest and need a credential capable of
relaying it onward, meaning the write leaf minted in
`ansible/cloud_credentials/create_snapshot_write_keys.py` would have to
live on `storage` instead of (or in addition to) `security`. That cuts
against [0017](0017-openbao-bootstrap-secret-split.md)'s own reasoning
for putting this in a dedicated bucket in the first place: keeping
OpenBao's recovery path scoped to the host that actually holds OpenBao,
not folded into the general backup pipeline's trust surface. GPG's own
MDC means a compromised `storage` still can't read or usefully tamper
with the ciphertext — the risk isn't confidentiality, it's handing a
second host standing access to a recovery-critical credential, plus a
new silent-failure mode: a compromised or misbehaving relay host could
delay or drop the push before it ever reaches R2/B2, a failure mode the
direct-push design doesn't have (it either pushes in the same run the
operator is watching, or fails loudly in front of them, as it did
during real testing — see that doc's "Before first use").

## Decision

`snapshot-push.sh` pushes directly from `security` to R2/B2 via
`rclone copy`, in the same run as the snapshot save and GPG encryption.
It never touches SeaweedFS or `cloud_sync`. The write leaf
(`create_snapshot_write_keys.py`) is minted and cached only on
`security`.

## Consequences

`storage` remains uninvolved in OpenBao's backup pipeline entirely —
compromising it yields nothing toward this recovery path, matching the
same per-host credential containment [0006](0006-backup-credential-blast-radius-threat-model.md)
established for every other app's backup, just via a different
mechanism (never granting the credential at all, rather than scoping
it once granted).

The trade-off this accepts: no shared scheduling infrastructure.
`controller`'s AppRole now provides a credential safe to leave on disk
for an unattended job, but there's nowhere unattended to run it from
yet — `controller` is the operator's own machine, never meant to run
scheduled jobs. Until a dedicated automation host exists, this runs by
hand, authenticating as `controller`'s AppRole rather than the root
token (see
`docs/openbao-backup-restore.md`'s "Why manual" section). Once that
host exists, the natural next step is `snapshot-push.sh`'s own
systemd timer on `security` — the same shape `cloud_sync` already is
(a standalone timer, not living inside `backup_agent`), not an
integration with the existing pipeline.
