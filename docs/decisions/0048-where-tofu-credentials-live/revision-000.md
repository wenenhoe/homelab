---
id: ADR-0048
revision: 0
type: adr
title: Where Tofu's own credentials live
short: Tofu credentials
solution: 'A file on the host that runs Tofu, outside the repo and outside OpenBao'
summary: Where the Proxmox and OPNsense API credentials and Tofu's state-backend credential live, given the store may be what is being provisioned.
topic: secrets-store
status: accepted
related: [ADR-0013, ADR-0018, ADR-0020, ADR-0026]
---

# 0048. Where Tofu's own credentials live

## Context

Tofu needs standing credentials before it can provision anything: a
Proxmox API token, an OPNsense API key once its day-2 configuration is
managed, and an S3 credential once its state has a remote backend
([`vm-provisioning.md`](../../topics/infra/vm-provisioning.md#state-backend--secrets)).
Every other secret in this repo lives in OpenBao on `security`
([0013](../0013-secret-storage/revision-000.md)
through
[0026](../0026-detecting-reads-of-high-value-secrets/revision-000.md)),
so the question is whether these can too, against the constraint below.

The real fork is a bootstrapping-order problem specific to Tofu: it
may need to provision `security` itself — the host that runs the only
OpenBao instance that exists today — before that instance is
reachable. No other secret consumer in this repo has that problem,
since Ansible only ever runs against hosts that already exist.

This is a **standing constraint**, not a one-time migration-day concern.
`vm-provisioning.md`'s VMID scheme lists the 2XX range's purpose as
"Primary target — current managed hosts + OPNsense", and
`tofu-vm-provisioning.md` (removed; replaced by: `tofu-migration.md`)'s environment table lists `security` (VMID
205) as one of exactly those hosts. The migration's rebuild on the real
VMID ranges names no carve-out for `security`, so once cut over it is an
ordinary Tofu-managed host like every other 2XX host, and every later
resize or rebuild hits the bootstrapping order again.

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

Tofu reads this file when it starts. The file is the only copy of these
credentials on the Tofu host, so losing it costs re-issuing each one from
its source (the Proxmox node, OPNsense, the state backend's S3
identities), not data. Whoever can read the file on the Tofu host holds control of the
hypervisor, so the host and the account that owns the file are part of
the trust boundary; [ADR 0058 (Operator work host)](../0058-where-operator-work-runs/revision-000.md)
puts Tofu on a host that handles no untrusted content.

Planned, not decided here: an OpenBao on the host that runs Tofu,
seeded from a snapshot pulled from the main instance (the counterpart of
the existing snapshot push; the pull does not exist yet). That would
replace the file with a new revision of this lineage once built, and
moving the credentials would then be a migration of live credentials.
