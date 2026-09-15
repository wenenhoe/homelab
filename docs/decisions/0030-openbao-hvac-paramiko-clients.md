---
id: ADR-0030
title: "Adopt hvac + paramiko for every internal OpenBao/SSH client, not just cloud_credentials"
type: adr
status: accepted
---

# 0030. Adopt hvac + paramiko for every internal OpenBao/SSH client, not just cloud_credentials

**Status:** Accepted

## Context

`cache.py` (`ansible/cloud_credentials`) and `bootstrap_secrets.py`
each independently hand-rolled an OpenBao AppRole login + KV v2
read/write over raw `requests`, and each independently fetched
step-ca's root cert via `ssh ... docker exec step-ca cat
root_ca.crt` as a raw `subprocess` call. The duplication had already
produced the same bug twice, independently: neither file's SSH-fetch
`subprocess.run` call set a timeout, so an unreachable `security` host
or a network partition blocked either one forever - fixing one without
the other left the second stale.

Two more files shared this surface: `audit_secrets.py` read the same
OpenBao KV v2 paths over its own `requests` calls (its B2/OCI
provider-API calls are a separate concern, covered by
[ADR 0029](0029-cloud-credentials-selective-sdk-adoption-not-blanket-swap.md)),
and `docker/openbao/watcher/r2_read_watcher.py` - a standing,
continuously-running watcher rather than a one-shot script - did the
same over its own loopback `requests` calls (no SSH/root-cert fetch
there; it runs on `security` itself).

Considered and rejected up front: `docker/openbao/scripts/`'s three
shell scripts and `openbao_backup/snapshot-push.sh.j2` wrap the
official `bao` CLI directly, not a hand-rolled HTTP reimplementation -
a different kind of problem, tracked separately in
[`openbao-cli-standardization.md`](../projects/openbao-cli-standardization.md),
not folded into this decision.

Whether the four Python clients above should also share code with
each other (rather than each independently adopting `hvac`/`paramiko`)
was originally an open question in this draft. It's answered
elsewhere now: `hvac` login/read/write bodies turned out
byte-identical across `cache.py`, `bootstrap_secrets.py`, and
`r2_read_watcher.py` once all three were built, and separately,
`cache.py`'s generic OpenBao/host-resolution helpers (`_main_domain`,
`_security_ssh_target`, the Vault session logic) turned out to already
be needed by consumers with nothing to do with cloud credentials
(`docker/openbao/scripts/bao-*.sh`, `restore_hosts_scope_from_backup.py`).
Both facts are folded into
[`tools-directory-and-secrets-package-split.md`](drafts/tools-directory-and-secrets-package-split.md)'s
larger reorganization instead of being decided independently
here - that draft's Option B already presupposes the shared client
this decision's Context motivated.

`r2_read_watcher.py`'s standing-process shape raised a real question -
whether a long-lived watcher needs token renewal or reconnect-with-
backoff that a one-shot script wouldn't exercise. It doesn't: its
Vault login happens once at startup to fetch Telegram's alerting
secrets, and the long-running `docker logs -f` watch loop that follows
never receives or reuses that token - a token expiring hours or months
later is irrelevant, since nothing ever presents it again.

## Decision

Every internal Python client that talks to OpenBao directly
(`cache.py`, `bootstrap_secrets.py`, `audit_secrets.py`,
`r2_read_watcher.py`) uses `hvac` for the Vault client and, where an
SSH hop to fetch step-ca's root cert is needed (`cache.py`,
`bootstrap_secrets.py` - not `r2_read_watcher.py`, which runs on
`security` itself over loopback), `paramiko` instead of `subprocess` +
the `ssh` CLI. Confirmed live against a real OpenBao instance and a
real `security` host: `hvac.Client(url=..., verify=ca_path)` +
`auth.approle.login()` composes cleanly with each file's existing
per-process temporary-CA-file session pattern, `client.token` matches
the raw auth response, `read_secret_version()`'s
`["data"]["data"]["value"]` shape matches what each file's own
hand-rolled read already walked, and `paramiko`'s
`load_system_host_keys()` + `AutoAddPolicy()` reproduces
`StrictHostKeyChecking=accept-new`'s trust-on-first-use exactly
(`BadHostKeyException` on a mismatch against an already-known host,
regardless of policy - the same fail-closed shape, confirmed against
the real host).

Whether the four resulting clients also share an implementation with
each other, and where that implementation lives, is
`tools-directory-and-secrets-package-split.md`'s decision to make, not
this one's - this decision is limited to which libraries every
internal client uses, independent of how much code they share.

## Consequences

- All four clients' missing-SSH-timeout bug is fixed, bounded to
  `_TIMEOUT_SECONDS = 10` in each - `ansible/cloud_credentials/cache.py`
  and `ansible/bootstrap_secrets.py` are the reference
  implementations for the SSH-fetch + session pattern;
  `docker/openbao/watcher/r2_read_watcher.py` for the no-SSH,
  login-once-at-startup variant.
- `hvac`'s own upcoming v3.0.0 default change
  (`raise_on_deleted_version`) is pinned explicitly to `True`
  (preserving current behavior) in every read call, rather than left
  to silently flip later.
- Each of the four clients still independently implements the same
  login/read/write bodies today - accepted as a known, temporary
  consequence of this decision alone; whether that duplication gets
  addressed is scoped entirely to
  `tools-directory-and-secrets-package-split.md`, not reopened here.
