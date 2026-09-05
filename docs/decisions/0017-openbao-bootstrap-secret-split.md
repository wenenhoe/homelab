# 0017. Split secrets into recovery-critical and operational classes for OpenBao bootstrap

**Status:** Proposed

## Context

OpenBao is the planned replacement for [0001](0001-credential-caching-stage-1-before-secrets-manager.md)'s
file cache (see `cloud-credential-creation.md` for what's cached
today). If every credential — including the ones needed to fetch and
restore OpenBao's own backup — lives only inside OpenBao, a sealed or
lost instance can't be brought back: nothing exists yet to authenticate
to cloud storage and pull the snapshot that would unseal it.

**Threat model.** The scenario this decision defends against is total
loss of the `security` host running OpenBao — disk failure, host
rebuild, or a compromise requiring a clean rebuild — with recovery
depending entirely on what survives outside that host. This is
distinct from [0013](0013-backup-credential-blast-radius-threat-model.md)'s
threat model (a compromised app host reaching the offsite backup): this
one assumes the thing being restored *is* the credential store itself,
so nothing stored only inside it can be part of its own recovery path.

Two real alternatives were considered:

- **Everything in Vault, cloud auto-unseal as the escape hatch.** A
  cloud KMS could unseal OpenBao automatically on boot, sidestepping
  Shamir shares — but the KMS credential enabling that has the same
  chicken-and-egg problem one level up: it would need to live outside
  Vault too, and now there's a second offline secret to manage instead
  of one. Auto-unseal also adds a live dependency on a cloud provider
  for every boot, not just disaster recovery. Rejected for this
  decision; still a live question for the separate unseal-method
  choice (Shamir vs. auto-unseal), which this ADR doesn't resolve.
- **Keep the whole file-based cache as a permanent fallback
  alongside Vault.** Rejected per this migration's stated goal —
  replacing the cache, not running both indefinitely — and it would
  leave two authoritative sources for the same operational secrets,
  reintroducing the drift problem a secrets manager exists to remove.

## Decision

Split secrets into two classes:

- **Recovery-critical** — must exist before OpenBao does. This is
  exactly two things: the Shamir unseal key shares, and one narrowly
  scoped **read-only** cloud credential limited to OpenBao's own
  snapshot bucket/prefix. Both live outside Vault permanently, with the
  same offline handling this repo already gives its GPG private key —
  password manager plus one offline copy, never committed, never only
  on a host.
- **Operational** — everything else: day-to-day cloud write/read
  credentials, app secrets, everything currently driven by
  `secrets_registry.yaml`. Fine to live only in Vault once it's up.

Bootstrap/restore order: offline break-glass bundle → bare host with
OpenBao installed → fetch the raft snapshot using the scoped read-only
key → restore snapshot and unseal → Ansible authenticates via AppRole →
restore playbook pulls everything else from Vault.

## Consequences

- The scoped read-only snapshot credential is a *new* credential
  category for `ansible/cloud_credentials/` — narrower than any
  existing leaf credential (bucket/prefix-limited, read-only,
  provisioned outside the rotation machinery those scripts drive today,
  since it can't depend on the thing it's bootstrapping). Which
  provider hosts the snapshot bucket, and how this credential is
  minted and refreshed, is a build detail for OpenBao's initial
  deployment and the backup/restore proving work that follows it, not
  decided here.
- This adds a second offline secret to the operator's break-glass
  process (the Shamir shares) alongside the existing GPG key, and a
  second narrowly-scoped credential outside any automated rotation.
  Both are one-time, human-attended items, consistent with how this
  repo already treats the GPG key and initial rotation-key bootstrap
  ([0001](0001-credential-caching-stage-1-before-secrets-manager.md)).
- The migration roadmap's backup/restore proving stage — proving the
  backup/restore loop before any secret's authoritative copy moves
  into Vault — is the actual test of this split, see
  `docs/disaster-recovery.md` once that stage lands for the drill
  procedure.
