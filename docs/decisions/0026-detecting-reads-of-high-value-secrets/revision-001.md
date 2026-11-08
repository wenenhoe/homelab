---
id: ADR-0026
revision: 1
type: adr
title: Detecting reads of high-value secrets
short: High-value secret read alerts
solution: Match request lines and watch every secret-bearing rotation credential, not only R2's
summary: Every read of a rotation credential that can mint or revoke other credentials is visible and raises an alert.
topic: secrets-store
status: accepted
supersedes: 0
related: [ADR-0110, ADR-0020]
---

# 0026. Request-line matching, and watching all three rotation credentials

## Context

[Revision 0](revision-000.md) watches one Vault path: the R2 rotation
token's. Two things in it no longer match what is built or what it is
meant to protect.

**The matched line type.** Revision 0 says the watcher matches
`type: "response"` lines. The watcher
([`rotation_read_watcher.py`](../../../docker/openbao/watcher/rotation_read_watcher.py))
matches `type: "request"` lines instead, and its docstring gives the
reason: one read writes both a `request` and a `response` line carrying the
same path, so matching either alone avoids a double alert. The request line
is the better choice and stays. It is written before the read is served, so
a read that fails, or whose response is never written, still alerts.

**The watched set.** Revision 0 watches the R2 token because it is
master-equivalent
([ADR 0110](../0110-the-r2-admin-token-as-the-rotation-credential/revision-000.md)).
B2's and OCI's rotation credentials are narrower than that, but "narrower"
is not "harmless": each can still create and delete the leaf credentials
for its provider, which is the whole of what the leaf credentials guard.
A read of either one was audited but raised nothing, so the one alerting
path in this design covered one of the three rotation credentials.

The secret-bearing paths, by provider:

| Provider | Secret-bearing path | Identifier-only paths (not watched) |
| --- | --- | --- |
| R2 | `_rotation-key-cloudflare-r2-token` | none |
| B2 | `_rotation-key-backblaze-b2-application-key` | `…-b2-key-id` |
| OCI | `_rotation-key-oci-client-secret` | `…-oci-client-id`, `…-oci-app-id`, `…-oci-domain-url`, `…-oci-created-at` |

All paths sit under `secret/data/cloud_credentials/rotation/`. An identifier
alone authenticates nothing, so alerting on it would add noise without
adding detection.

**Expected alerts.** The weekly credential check reads all three secrets, so
it raises three alerts, one per watched path, all naming the same role. That
trio is the accepted signal that the check ran; an alert at any other time,
or naming another role, is not expected.

## Decision

Keep everything in revision 0 that this revision does not change: the
declarative `audit "file"` device on stdout, the capped `json-file` log,
the dedicated read-only AppRole, the heartbeat, and the live-tail shape.

Change the watcher in two ways:

1. **Match request lines.** Match `type: "request"` lines with
   `operation: "read"`, as the script already does. Revision 0's wording is
   superseded on this point.
2. **Watch a set of paths.** Replace the single `TARGET_PATH` with a fixed
   set holding the three secret-bearing paths in the table above. A read of
   any member alerts. The alert names the secret that was read, so the
   weekly trio can be told apart from a stray read. Adding a rotation
   credential later is a one-line change to the set plus a row in the
   table, not a new ADR.

The watcher still keeps one resume record, the last alerted line's time and
request id, because all paths come from one log stream and one ordering.
The record's boundary check is unchanged. Nothing else about its
authentication or reach changes: the AppRole stays read-only on the
Telegram path alone.

## Alternatives considered

- **Alert on every path under `cloud_credentials/rotation/`.** Rejected: it
  also fires on the identifier-only paths, so one weekly run would raise
  about eight alerts and the useful ones would be lost in them.
- **Alert on every path under `cloud_credentials/`, leaf credentials
  included.** Rejected for the same reason, and because leaf credentials are
  read by design on every backup and restore.
- **Leave B2 and OCI unwatched, relying on their narrower scope.** Rejected:
  narrower scope limits what a stolen credential can reach, but it does
  nothing to tell the operator it was read.

## Consequences

- Every weekly credential check raises three alerts instead of one, which
  the [watcher doc](../../topics/secrets/openbao-rotation-read-watcher.md)
  explains.
- The watcher no longer watches R2 alone, so it is named
  `rotation-read-watcher`.
- "Genuinely narrower", said of B2's and OCI's rotation keys, is a
  difference in blast radius and not in how closely each is watched.
- Matching more than one path adds a lookup per audit line and nothing
  else. The "parsed only far enough to check the path, then discarded"
  rule from revision 0 still holds.
- The accepted limits from revision 0 stand: the audit stream is plaintext
  for paths and policies and stays on `security`, and nothing reduces what
  OpenBao logs.
