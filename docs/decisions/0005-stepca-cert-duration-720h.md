# 0005. step-ca cert duration set to 720h, not step-ca's own 24h default

**Status:** Accepted, flagged for review — the premise below has since
changed and this hasn't been revisited.

## Context

step-ca's own default (24h) assumes a consumer is always renewing in
the background. At the time this value was chosen, nothing in this
repo did that — a 24h cert would have expired unattended, since the
reference setup's own renewal automation
(`stepca-provision.sh`/`stepca-renew.sh`) hadn't been adapted yet.

## Decision

Set the default provisioner's claim duration to 720h via `step ca
provisioner update --x509-default-dur` (see
[ADR 0004](0004-stepca-custom-entrypoint-not-docker-init-vars.md)),
rather than step-ca's own 24h default.

## Consequences

`lldap_cert`'s systemd `cert-renewer@` timer (see
[`lldap.md`](../lldap.md)) is now exactly the renewal automation that
720h was chosen to route around not having — and it's been live since
before this ADR was written. **This value hasn't been reconsidered
since that changed.** Moving back toward step-ca's own 24h philosophy
(shorter-lived certs, smaller revocation-risk window) is worth doing
as a deliberate follow-up now that the automation this decision was
originally waiting on already exists — not as a side effect of an
unrelated change.
