---
id: ADR-0008
revision: 0
type: adr
title: Internal certificate lifetime
solution: 720h default provisioner claim duration
summary: How long certificates from the internal CA live, given the renewal automation that exists.
topic: ingress-tls-pki
status: accepted
related: [ADR-0007]
---

# 0008. step-ca cert duration set to 720h, not step-ca's own 24h default

**Status:** Accepted — see
[`0008-internal-certificate-lifetime/revision-001.md`](revision-001.md)
for the follow-up this ADR's own Consequences called for.

## Context

step-ca's own default (24h) assumes a consumer is always renewing in
the background. At the time this value was chosen, nothing in this
repo did that — a 24h cert would have expired unattended, since the
reference setup's own renewal automation
(`stepca-provision.sh`/`stepca-renew.sh`) hadn't been adapted yet.

## Decision

Set the default provisioner's claim duration to 720h via `step ca
provisioner update --x509-default-dur` (see
[ADR 0007](../0007-internal-ca-initialization-and-identity-persistence/revision-000.md)),
rather than step-ca's own 24h default.

## Consequences

`step_ca_cert`'s systemd `cert-renewer@` timer (see
[`lldap.md`](../../lldap.md)) is now exactly the renewal automation that
720h was chosen to route around not having — and it's been live since
before this ADR was written. Moving back toward step-ca's own 24h
philosophy (shorter-lived certs, smaller revocation-risk window) is
scoped in
[`0008-internal-certificate-lifetime/revision-001.md`](revision-001.md)
rather than left as an untracked note here.
