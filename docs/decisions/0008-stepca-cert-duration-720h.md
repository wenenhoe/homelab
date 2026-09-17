---
id: ADR-0008
title: "step-ca cert duration set to 720h, not step-ca's own 24h default"
type: adr
status: accepted
---

# 0008. step-ca cert duration set to 720h, not step-ca's own 24h default

**Status:** Accepted — see
[`stepca-shorten-cert-duration-now-that-renewal-exists.md`](drafts/stepca-shorten-cert-duration-now-that-renewal-exists.md)
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
[ADR 0007](0007-stepca-custom-entrypoint-not-docker-init-vars.md)),
rather than step-ca's own 24h default.

## Consequences

`step_ca_cert`'s systemd `cert-renewer@` timer (see
[`lldap.md`](../lldap.md)) is now exactly the renewal automation that
720h was chosen to route around not having — and it's been live since
before this ADR was written. Moving back toward step-ca's own 24h
philosophy (shorter-lived certs, smaller revocation-risk window) is
scoped in
[`stepca-shorten-cert-duration-now-that-renewal-exists.md`](drafts/stepca-shorten-cert-duration-now-that-renewal-exists.md)
rather than left as an untracked note here.
