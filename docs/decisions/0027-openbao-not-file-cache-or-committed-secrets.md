# 0027. Adopt OpenBao, not a continued file cache or git-committed encrypted secrets

**Status:** Accepted

## Context

[0013](0013-credential-caching-stage-1-before-secrets-manager.md)
deferred a real secrets manager, caching credentials in files instead
as an interim stage-1 approach — and named its own limits at the time:
no audit trail of who/what accessed a given credential, no
per-credential access control beyond file permissions. Two things
made that untenable as the repo grew:

- The file cache became unwieldy at scale as more secrets accumulated
  across more hosts and apps.
- Centralized rotation and audit weren't achievable within a flat file
  cache in practice, not just in principle —
  [0015](0015-credential-expiry-native-where-possible-self-tracked-where-not.md)/
  [0016](0016-oci-expiry-via-scim-not-self-tracked-cache-files.md) show
  this directly: credential expiry needed a mix of native provider
  expiry and self-tracked cache-file timestamps, checked by a systemd
  user timer on `controller` — a workaround for the lack of any real
  lifecycle tracking, not a fix for it.

Separately: a standing concern about future AI-agent tooling (e.g.
Claude Code) having direct read access to a plaintext secrets cache on
disk, if such tooling were ever given file/repo access.

Ansible Vault and SOPS (with `age` as its typical backend) were both
considered and rejected for the same underlying reason: both are built
around encrypting secrets for safe git commit — SOPS especially, being
designed around exactly that GitOps pattern — and the goal here was to
avoid committing secret material to the repo at all, encrypted or not,
not just to avoid committing it in plaintext.

## Decision

Adopt OpenBao — a standing, network-reachable secrets store — instead
of any git-committed encrypted-file approach or a continued file
cache. See ADRs
[0017](0017-openbao-bootstrap-secret-split.md) through
[0026](0026-openbao-audit-device-and-r2-per-read-watcher.md) for the
implementation this decision was built from, in sequence.

## Consequences

Every secret this repo manages now depends on OpenBao being reachable
— a new operational dependency the file cache didn't have, addressed
by 0017's bootstrap-secret split and
[`openbao-backup-restore.md`](../openbao-backup-restore.md)'s backup
mechanism. [0013](0013-credential-caching-stage-1-before-secrets-manager.md)
is superseded by this decision. Implementation detail —
bootstrapping, auth, backup/restore, migration — lives in ADRs
0017–0026 and the `openbao-*.md` topic docs, not repeated here.
