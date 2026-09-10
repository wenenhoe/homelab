# A dedicated BIND9 on `security` for Tofu-provisioned VM DNS

**Status:** Draft

## Context

Today, `services`' BIND9 is the lab's single authoritative internal
nameserver: it aggregates every app host's `dns_zones` from
`host_vars` and auto-generates CNAMEs for anything with a `caddy`
route ([`bind9.md`](../../bind9.md)). `vm-provisioning.md`'s original
Phase 2 plan pointed Tofu-provisioned VM A records somewhere different
— static host overrides pushed through OPNsense's own config API,
since Tofu assigns those VMs deterministic IPs at provision time and
they don't need OPNsense's DHCP-DDNS path at all.

Two other options exist beyond OPNsense's API. `services`' `bind9`
role already supports arbitrary static `extra_records` per zone,
rendered through a corruption-immune, no-dynamic-updates mechanism
(compare candidate content against live content with the serial
stripped, only write/reload on a real change) — nothing about that
role is structurally CNAME-only, so it could hold Tofu-sourced A
records too. Staying with OPNsense's API is also still technically
sound as scoped: it only ever needed ordinary record management
through the plugin's own supported model, not raw zone-file editing,
which is the thing that plugin doesn't support.

Neither of those is the direction being pursued, for two reasons.
First, coupling: `services`' zone data comes from `host_vars`/
`app_registry`, resolved at Ansible render time; Tofu-provisioned VM
data would come from the not-yet-built Tofu→Ansible inventory
generator (Stage 4), resolved from Tofu's own state/outputs. Feeding
both into one role's render pipeline ties two independently-evolving
data sources together for no structural reason. Second, an
OPNsense-API-driven design is the one piece of this repo's DNS story
that would depend on a live, writable API call succeeding during
deploy — everything else here (`services`' BIND9 included) is
Ansible-rendered and reloadable offline, consistent with the top-level
README's own "no manual step beyond `ansible-playbook`" framing.
Trust-tier separation is a secondary benefit: infrastructure IP
topology for Tofu-managed hosts sits on `security`, a similar
placement rationale to why OpenBao lives there rather than being
bolted onto an existing host.

## Decision

A second, dedicated BIND9 instance on `security`, authoritative only
for A records of Tofu-provisioned VMs — separate from `services`'
CNAME zone, fed by the Tofu→Ansible inventory generator's output
instead of `host_vars`/`app_registry`. It reuses the same
render-diff-reload mechanism `services`' `bind9` role already proves
out, either as a parameterized version of that role or a close sibling
— which of the two isn't decided here (see Assumptions).

OPNsense's own BIND plugin drops out of the Tofu-VM DNS story
entirely under this design. It keeps its existing job: Kea-DDNS for
the `.50`–`.254` dynamic pool, which still needs it and still carries
that class of journal-corruption risk unavoidably, since that pool is
for devices Tofu doesn't manage.

The exact mechanism for how clients resolve both zones coherently —
NS delegation from `services`' zone to `security`'s new one, two
independently-queried zones, or something else — isn't designed here.

## Assumptions

- **Claim:** the Tofu→Ansible inventory generator (Stage 4) produces
  VMID/IP/hostname data in a shape a `bind9`-style role can consume
  without a translation layer.
  **Breaks if wrong:** if Stage 4's real output shape doesn't map
  cleanly onto something like `host_vars`' `dns_zones`/`extra_records`
  structure, this design needs an adapter step it doesn't currently
  account for.
  **Checked by:** once Stage 4 is actually built.
- **Claim:** two authoritative zones on two different hosts can be
  properly delegated (or otherwise coherently queried) without
  disrupting `services`' existing zone behavior.
  **Breaks if wrong:** if delegation turns out awkward — BIND's own
  NS-delegation model not fitting cleanly across two independently
  Ansible-managed hosts, or clients needing to be told to query two
  resolvers directly — the "separate authoritative island" design may
  need to collapse back into one host after all.
  **Checked by:** a real delegation test between two `bind9`-role
  instances, once Stage 4's data shape is known and this stage is
  actually being built — not resolvable by reading code alone.
- **Claim:** running a second instance of this mechanism costs
  meaningfully less than the coupling/API-dependency problems it
  avoids.
  **Breaks if wrong:** if the second instance needs substantially
  different handling than `services`' — different deploy ordering,
  its own DNS self-resolution bootstrapping alongside whatever
  `security` already does for OpenBao/step-ca's own resolution needs
  — the "reuse a proven pattern cheaply" argument weakens.
  **Checked by:** when the role/module is actually built.

## Consequences

If this is promoted, `bind9.md` and the top-level README's "single
authoritative BIND9 instance" framing both need updating — that
description stops being accurate the moment a second authoritative
zone exists. `vm-provisioning.md`'s OPNsense Phase 2 section also
needs rewriting, since the static-host-override design it currently
describes is what this supersedes. Neither is a decision recorded
here — a real fork with real consequences, not a formality.
