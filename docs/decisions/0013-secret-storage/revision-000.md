---
id: ADR-0013
revision: 0
type: adr
title: Secret storage
short: Secret storage
solution: A flat-file cache under ansible/files/secrets/
summary: Where the repo's secrets and credentials live, and who and what can read them.
topic: secrets-store
status: superseded
superseded_by: 1
---

# 0013. Secret storage

## Decision

Cache every credential — rotation keys/tokens and leaf credentials
alike — to `ansible/files/secrets/`, the same flat-file convention
every other secret in this repo already uses (see
[`secrets.md`](../../topics/secrets/secrets.md)). No separate secrets-manager dependency
for this subproject.
