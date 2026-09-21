---
id: DRAFT-stepca-shorten-cert-duration-now-that-renewal-exists
title: "Shorten step-ca's default claim duration now that cert-renewer@ exists"
type: draft-adr
status: draft
---

# Shorten step-ca's default claim duration now that cert-renewer@ exists

**Status:** Draft

## Context

[ADR 0008](../0008-internal-certificate-lifetime/revision-000.md) set step-ca's default
provisioner claim duration to 720h instead of step-ca's own 24h
default, because at the time nothing in this repo renewed certs
automatically — a 24h cert would have expired unattended. That ADR
already flags itself "Accepted, flagged for review": the renewal
automation it was routing around not having now exists and live
(`step_ca_cert`'s `cert-renewer@` systemd timer, one instance each for
`lldap` and `openbao` — confirmed via `docs/lldap.md`'s and
`docs/openbao.md`'s own reference to it), and the duration was never
reconsidered afterward.

The duration is set once, provisioner-wide
(`step ca provisioner update --x509-default-dur`, per
[ADR 0007](../0007-internal-ca-initialization-and-identity-persistence/revision-000.md)),
so it applies identically to both of step-ca's real consumers — there's
no per-service override to reason about separately.

The renewal timer itself
(`ansible/roles/step_ca_cert/templates/cert-renewer@.timer.j2`) runs
every 15 minutes (`OnCalendar=*:1/15`), with a 5-minute randomized
jitter — a check interval two to three orders of magnitude finer than
even step-ca's own 24h default duration. `step ca renew`'s own client
renews well before actual expiry (within a fraction of the cert's
remaining life, not at the last possible moment), so this timer
granularity gives enormous margin for a much shorter duration than
720h — the original 720h value was sized for a world with no automated
renewal at all, not tuned against the automation that now exists.

## Decision

Move the default provisioner's claim duration from 720h back toward
step-ca's own 24h default, shrinking the revocation-risk window ADR
0008's Consequences already names as the reason to do this. Land the
new value via the same `x509-default-dur` mechanism ADR 0007
established, with no change to `cert-renewer@`'s timer schedule —
15-minute checks already have ample margin for a 24h duration.

## Assumptions

- **Claim:** both `lldap` and `openbao`'s `cert-renewer@` instances
  actually renew successfully, well before expiry, at a shortened
  duration — not just that the timer fires on schedule, but that a
  real renewal completes and the new cert is picked up by both
  consuming services without a restart race or stale-cert window.
  **Breaks if wrong:** a duration this short could turn a renewal
  hiccup (a transient step-ca outage, a network blip) into an actual
  outage far sooner than 720h ever would have, trading revocation-risk
  window for renewal-fragility exposure — the opposite of a clear win.
  **Checked by:** `ansible/roles/step_ca_cert/molecule/renewal_timing/`
  already exists and exercises provisioner duration changes
  (`step ca provisioner update admin --x509-min-dur=1m` appears in its
  `converge.yml`) — extend that scenario to the actual candidate
  value and confirm a real renewal round-trip succeeds for both
  `lldap` and `openbao`'s instances before rolling this out live.
- **Claim:** 24h specifically (step-ca's own default) is the right
  target, not some other value in between 24h and 720h.
  **Breaks if wrong:** if the Molecule spike above surfaces any
  friction at 24h specifically (e.g., renewal timing interacting badly
  with `AccuracySec=1us`/jitter at that duration), a longer-but-still-
  much-shorter-than-720h value might be the better outcome — this
  isn't a foregone "must be exactly 24h."
  **Checked by:** the same Molecule spike above; pick the final value
  based on what it actually shows rather than defaulting to step-ca's
  number because it's the vendor default.

## Consequences

- Once decided, [ADR 0008](../0008-internal-certificate-lifetime/revision-000.md)'s
  "flagged for review" status line should be updated to point here
  rather than staying an open-ended flag with no tracked resolution.
- No compose/role changes beyond the one `x509-default-dur` value and
  whatever the Molecule spike's findings require — this is a
  parameter change, not new infrastructure.
- If the spike surfaces real renewal fragility at any short duration,
  the fallback is simply: leave 720h as-is, and record that finding in
  this draft's Context rather than silently abandoning the idea.
