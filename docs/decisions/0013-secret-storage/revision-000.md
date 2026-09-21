---
id: ADR-0013
revision: 0
type: adr
title: Secret storage
solution: A flat-file cache under ansible/files/secrets/
summary: Where the repo's secrets and credentials live, and who and what can read them.
topic: secrets-store
status: superseded
superseded_by: 1
---

# 0013. Cache cloud credentials to disk before adopting a secrets manager

**Status:** Superseded by [revision 001](revision-001.md)

## Context

`create_rotation_keys.py`/`create_leaf_keys.py` mint and rotate six R2/
B2/OCI credentials (write + read per provider) plus each provider's
rotation key/token. Something has to persist them between runs.

The alternative — standing up a dedicated secrets manager (OpenBao is
the current candidate) before writing any of this — would add a new
always-on service, its own unseal/backup story, and an access-control
layer to design, before a single credential could be minted. That's a
real subproject on its own, unrelated to the credential-scoping logic
these scripts exist to get right per provider.

## Decision

Cache every credential — rotation keys/tokens and leaf credentials
alike — to `ansible/files/secrets/`, the same flat-file convention
every other secret in this repo already uses (see
[`secrets.md`](../../secrets.md)). No separate secrets-manager dependency
for this subproject.

## Consequences

Anything with filesystem access to `ansible/files/secrets/` can read
every cached credential in plaintext — no audit trail of who/what
accessed a given key, no per-credential access control beyond the
directory's own file permissions. Acceptable for a single-operator
homelab controller; would not scale to multiple operators or a
compliance requirement.

Migrating to an actual secrets manager is intentionally deferred as a
separate, not-yet-scoped project — nothing in the current design
blocks it later. R2's cached admin token specifically won't reach
parity with B2's/OCI's rotation keys even after that migration (see
[0014](../0014-r2-rotation-credential-cannot-be-narrowed/revision-000.md)) — a
secrets manager narrows *who/what can reach* that token, not *what it
can do* once reached.

See [`cloud-credential-creation.md`](../../cloud-credential-creation.md)
for what each cached credential is scoped to, provider by provider.
