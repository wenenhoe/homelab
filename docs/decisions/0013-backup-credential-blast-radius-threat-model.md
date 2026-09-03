# 0013. Threat model: scope credentials so a compromised app host can't reach the offsite backup

**Status:** Accepted

## Context

**Threat model.** The adversary this design assumes is a compromised
app host (`services`, `security`, or `play`) — not a compromised
`storage`, and not a network-level attacker. The asset being protected
is the offsite backup itself: the whole point of having one is
surviving compromise of the host it's protecting, so whatever
credential that host holds is exactly as dangerous as the access it
grants. Before this design, that risk was live: every app host's
`backup_agent` holds a write-capable credential by necessity (it has
to be able to write its own backups somewhere), so the question is how
far that credential's reach extends if the host holding it is fully
compromised.

## Decision

Two structural constraints, both derived directly from the threat
model above:

- **Cloud credentials never touch an app host.** R2/B2/OCI write
  access exists only on `storage` (`cloud_sync`) — the smallest,
  least-exposed host in the fleet (nothing user-facing runs there).
  Compromising `services`, `security`, or `play` yields no cloud
  credential of any kind, only that host's own narrow SeaweedFS access
  below.
- **Each app host's SeaweedFS identity is scoped to its own prefix
  only** (`docker/seaweedfs/configs/s3-identity.json.j2`,
  `Write:homelab-backups/<hostname>-*` etc.).

## Consequences

Compromising any single app host caps the damage at that host's own
SeaweedFS archives — it can't reach another host's archives, and it
can't reach any cloud credential at all. The residual risk this
accepts, not eliminates: a compromised `services` can still tamper
with `services`' own SeaweedFS archives, since whatever produces a
backup needs *some* write path to stage it — there's no way to give a
host a write path to its own backup without that path being available
to whatever's compromised on that host too.

This holds because `cloud_sync`'s own relay is `copy`-only (see
[ADR 0006](0006-cloud-sync-copy-not-sync.md)) — a compromised app host
tampering with its own SeaweedFS archives can't propagate that
tampering to the cloud copy, since `cloud_sync` never deletes or
overwrites there either.

**Verified, not just designed:** `ansible/roles/seaweedfs_bucket/molecule/identity_scoping`
renders the real `s3-identity.json.j2` against a live throwaway
SeaweedFS target with two fake backup hosts, and asserts cross-prefix
write/read are denied and Admin actions aren't available to a scoped
identity — see [`disaster-recovery.md`](../disaster-recovery.md#threat-model)
for the current state of that coverage, including which specific
assertions have and haven't independently hit a real failure yet.
