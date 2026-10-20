---
id: ADR-0048
revision: 0
type: adr
title: Where Tofu's own credentials live
short: Tofu credentials
solution: 'A file on the host that runs Tofu, outside the repo and outside OpenBao'
summary: Where the Proxmox and OPNsense API credentials and Tofu's state-backend credential live, given the store may be what is being provisioned.
topic: secrets-store
status: approved
related: [ADR-0013, ADR-0018, ADR-0020, ADR-0026]
---

# 0048. Where Tofu's own credentials live

## Context

Tofu needs standing credentials before it can provision anything: a
Proxmox API token from the start, an OPNsense API key once Phase 2
lands, and the S3 credential for its own state backend
(`opentofu-state` on `storage` —
[`vm-provisioning.md`](../../topics/infra/vm-provisioning.md#state-backend--secrets)).
The doc's original text assumed these stay outside OpenBao entirely,
mirroring `openbao_utils/bootstrap.py`'s pre-OpenBao file-cache pattern —
but that mechanism no longer exists in this repo. The OpenBao migration
([0013](../0013-secret-storage/revision-000.md)
through
[0026](../0026-detecting-reads-of-high-value-secrets/revision-000.md))
retired it, and every other secret in this repo now lives in OpenBao
on `security`. The original reasoning for keeping Tofu's secrets
separate doesn't hold as stated anymore, and a replacement for it has to be
chosen against the constraint below.

The real fork is a bootstrapping-order problem specific to Tofu: it
may need to provision `security` itself — the host that runs the only
OpenBao instance that exists today — before that instance is
reachable. No other secret consumer in this repo has that problem,
since Ansible only ever runs against hosts that already exist.

**Settled, not just assumed:** whether this is a one-time migration-day
concern or a standing constraint doesn't need to wait on Migration
Stage 2 actually happening — the project's own design already answers
it. `vm-provisioning.md`'s VMID scheme lists the 2XX range's purpose as
"Primary target — current managed hosts + OPNsense", and
`tofu-vm-provisioning.md`'s environment table lists `security` (VMID
205) as one of exactly those current managed hosts. Migration Stage 2
("rebuild on the real VMID ranges, cut over, decommission the old
VMs") names no carve-out for `security` — it gets rebuilt via Tofu
like `services`/`storage`/`play`. Once cutover happens, `security` is
an ordinary Tofu-managed host going forward, the same as every other
2XX host, with nothing in this project's design suggesting future
resizes or rebuilds would route around Tofu for `security` specifically.
This was resolvable by reading the existing design, not something
that requires the migration to actually happen first — an earlier
version of this draft's first Assumption incorrectly gated it on
Stage 6 landing, which would have made this draft unable to reach
`approved` before the very project it blocks was most of the way built.
The bootstrapping-order problem is therefore a **standing constraint**,
not a one-time migration-day concern — every future routine `security`
rebuild hits it again, not just the first one.

## Decision

Tofu's own credentials — the Proxmox API token, the OPNsense API key
and the state-backend S3 credential — live in a file on the host that
runs Tofu (an environment or `.tfvars` file). It sits outside the repo
and outside OpenBao, is readable only by the operator account, and is
never committed.

The reason is the bootstrapping order above, stated directly: Tofu has
to be able to rebuild `security`, which runs the only OpenBao, so
nothing Tofu needs in order to start can live in that OpenBao. This is
the same reasoning as Ansible's three permanent bootstrap exceptions
(`main-domain`, `openbao-controller-role-id`/`-secret-id`): access to
the store itself depends on them, so they can't live inside it.

All three credentials get the same treatment now. The OPNsense API key
is not deferred: it costs nothing extra in the same file, and a second
home for it would only add a lookup.

## Alternatives considered

- **Route through the existing OpenBao on `security`.** One Vault, one
  AppRole model, no new infrastructure, and `controller` already
  fetches secrets per run
  ([0020](../0020-automation-identity-and-access-scope/revision-000.md)).
  It loses because it breaks whenever `security` is what Tofu is
  (re)building, and per the Context that recurs on every rebuild, not
  once.
- **A dedicated Tofu-scoped OpenBao instance.** It solves the
  bootstrapping problem and gives Proxmox access, which controls every
  VM, its own trust tier. It loses for now because it is a second piece
  of standing infrastructure with its own deploy, backup and manual
  Shamir unseal
  ([0018](../0018-unsealing-the-secrets-store-after-restart/revision-000.md)),
  and there is no way yet to seed it from the main instance's backups
  other than by hand. Whether it reduces risk at all depends on its
  unseal and backup path being independent of the main instance's,
  which would need reasoning through before it is built.

## Consequences

Stage 1's secrets bootstrap reads this file, and the state-backend S3
credential is in it. The file is the only copy of these credentials on
the Tofu host, so losing it costs re-issuing each one from its source
(the Proxmox node, OPNsense, `storage`'s S3 identities), not data.
Whoever can read the file on the Tofu host holds control of the
hypervisor, so the host and the account that owns the file are part of
the trust boundary; [ADR 0058 (Operator work host)](../0058-where-operator-work-runs/revision-000.md)
puts Tofu on a host that handles no untrusted content.

Planned, not decided here: an OpenBao on the host that runs Tofu,
seeded from a snapshot pulled from the main instance (the counterpart of
the existing snapshot push; the pull does not exist yet). That would
replace the file with a new revision of this lineage once built, and
moving the credentials would then be a migration of live credentials.
