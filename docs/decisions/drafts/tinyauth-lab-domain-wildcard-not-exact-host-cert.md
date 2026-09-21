---
id: DRAFT-tinyauth-lab-domain-wildcard-not-exact-host-cert
title: "A second wildcard cert for tinyauth's own domain, closing its CT-log exposure"
type: draft-adr
status: draft
---

# A second wildcard cert for tinyauth's own domain, closing its CT-log exposure

**Status:** Draft

## Context

[ADR 0003](../0003-certificate-issuance-for-proxied-apps/revision-000.md) flags its own
`tinyauth` exception as "worth revisiting as a deliberate follow-up" —
folding `tinyauth` into the same per-host wildcard vhost everything
else uses, to close the one remaining CT-log exposure that ADR's
wildcard-by-default reasoning was meant to close entirely.

Checked against the actual template
(`ansible/roles/caddy/templates/Caddyfile.j2`) and `app_registry.yaml`'s
own comment on the entry: `tinyauth` isn't excluded by convention or
left over from an unfinished migration — it's excluded because it
lives at a genuinely different domain level. Every other app's `handle`
block matches `{{ route.host }}.{{ caddy_domain }}`, and `caddy_domain`
is **host-scoped** (e.g. `security`'s is `sec.{{ lab_domain }}`,
confirmed in that role's own Molecule fixtures). `tinyauth_forwarder`'s
`forward_auth` target, and `tinyauth`'s own site block, both use
`{{ tinyauth_host }}.{{ lab_domain }}` — one level up, shared across
every host in the fleet, not scoped to whichever host happens to be
rendering its own Caddyfile. `*.{{ caddy_domain }}`'s wildcard cert
genuinely cannot cover `tinyauth.{{ lab_domain }}`; these are different
certificate scopes, not a stylistic inconsistency. ADR 0003's "worth
revisiting" framing undersold this — folding `tinyauth` into any one
host's existing wildcard vhost was never actually on the table.

The CT-log exposure ADR 0003 cares about is still real, though: closing
it means requesting a *second* wildcard — `*.{{ lab_domain }}` — rather
than putting `tinyauth` inside an existing one. `lab_domain`
(`lan.{{ main_domain }}`) has exactly one inhabitant today
(`tinyauth`); nothing else in this repo's `app_registry.yaml` or
inventory currently issues a hostname at that level rather than under
some host's `caddy_domain`.

## Decision

Change `tinyauth`'s Caddyfile site-block address from
`{{ tinyauth_host }}.{{ lab_domain }}` to `*.{{ lab_domain }}`,
matched the same way the per-host wildcard vhosts already are, with
`tinyauth`'s own hostname handled via the same `handle`-block pattern
inside it. This requests one wildcard cert for `*.{{ lab_domain }}`
instead of an exact-name cert for `tinyauth.{{ lab_domain }}` — closing
the CT-log exposure the same way per-host wildcards already do for
every other app, without touching `caddy_domain`'s per-host scoping at
all.

## Assumptions

- **Claim:** nothing else in this repo currently expects, or will soon
  need, a hostname directly under `{{ lab_domain }}` (as opposed to
  under some host's `{{ caddy_domain }}`) — a `*.{{ lab_domain }}`
  wildcard would otherwise silently start matching and routing
  requests for anything added at that level straight to `tinyauth`'s
  upstream, which is the wrong behavior for anything that isn't
  `tinyauth`.
  **Breaks if wrong:** a future app or service placed at the
  `lab_domain` level would need an explicit carve-out in `tinyauth`'s
  site block (or a rethink of this Decision) rather than "just works"
  the way adding a `caddy_domain`-level app does today.
  **Checked by:** grepping `app_registry.yaml` and every `host_vars`
  file for any hostname pattern that resolves to `lab_domain` directly
  rather than `<host>.lab_domain`'s `caddy_domain` — a five-minute
  check, not a spike, before this is more than a plausible read.
- **Claim:** the DigitalOcean DNS-01 credentials this repo's ACME
  config already uses can issue a cert for `*.{{ lab_domain }}` with no
  additional scope/permission beyond what issuing `*.{{ caddy_domain }}`
  certs already needs — both are subdomains of the same `main_domain`
  zone the DNS-01 challenge already proves control of.
  **Breaks if wrong:** a second DNS-01 zone/credential scope would be
  needed, changing this from a one-line site-block edit into a real
  credentials change.
  **Checked by:** a live cert request against a real or staging ACME
  endpoint for `*.{{ lab_domain }}`, confirmed to succeed with the
  existing `cert_issuer acme` DigitalOcean config unmodified.

## Consequences

- `tinyauth`'s hostname stops being individually logged to public CT
  logs, closing ADR 0003's originally-stated gap in full.
- `app_registry.yaml`'s comment on the `tinyauth` entry
  ("isn't routed through the `*.{{ caddy_domain }}` wildcard vhost...")
  needs updating once this lands — it's still accurate about *why*
  (different domain level) but the routing mechanism it describes
  changes.
- If the first Assumption ever turns out false (something else needs
  a `lab_domain`-level hostname), this Decision needs revisiting before
  that thing ships, not after — a silently-swallowed request routed to
  `tinyauth`'s upstream instead of the intended app would fail in a
  confusing way, not loudly.
- Once this lands, ADR 0003's Consequences section should be updated
  to point here rather than still reading as an open thread.
