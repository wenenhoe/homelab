# 0010. Route most apps through one wildcard cert per host, not one cert per app

**Status:** Accepted, partially applied — see Consequences.

## Context

The original Caddy setup issued a separate DNS-01 cert per app, each
in its own site block (`app.svc.example.com { reverse_proxy ... }`).
That was changed early on (June 2026) to one `*.{{ caddy_domain }}`
wildcard vhost per host, with a `@matcher`/`handle` block per app
routed inside it.

Two real considerations motivate this, and it's genuinely unclear
which one drove the original change, since no rationale was recorded
at the time:

- **Config simplicity.** N apps under individual site blocks means N
  near-identical blocks to maintain; one wildcard vhost with N
  `handle` blocks is flatter and scales better as apps are added — a
  real, visible benefit in the diff that made this change.
- **Certificate Transparency logs.** Every publicly-issued cert —
  wildcard or not — gets logged to public CT logs (e.g. crt.sh). A
  cert for `app-name.example.com` publishes that exact hostname
  publicly, tied to the domain; a cert for `*.example.com` doesn't
  reveal any of the names it covers. This is a commonly cited reason
  in the self-hosting community for preferring wildcard certs
  specifically to avoid exposing which apps are running. Whether this
  was understood and intended at the time of the original change, or
  recognized only later, isn't clear from the history.

## Decision

Route apps through one wildcard vhost per host by default, matched by
`@app host app.{{ caddy_domain }}` + `handle` blocks inside it (see
[`caddy.md`](../caddy.md)), rather than a separate site block and cert
per app.

## Consequences

Adding an app is a new `handle` block inside the existing wildcard
vhost, not a new site block plus a new cert issuance.

**This isn't fully applied yet.** `tinyauth` still gets its own
individual site block and cert outside the wildcard vhost, since it's
the auth provider every other app's `handle` block calls out to via
`tinyauth_forwarder` — a real, deliberate exception, not an oversight.
Its hostname is still individually logged to CT logs as a result.
Fully closing the CT-log exposure this ADR's second consideration
cares about would mean routing `tinyauth` through the wildcard vhost
too; worth revisiting as a deliberate follow-up if that's a priority,
not something to change as a side effect of an unrelated change.
