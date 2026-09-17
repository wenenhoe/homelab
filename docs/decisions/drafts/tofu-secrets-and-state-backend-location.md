---
id: DRAFT-tofu-secrets-and-state-backend-location
title: "Where Tofu's own secrets and state-backend credential live"
type: draft-adr
status: de-risking
---

# Where Tofu's own secrets and state-backend credential live

**Status:** De-risking

## Context

Tofu needs standing credentials before it can provision anything: a
Proxmox API token from the start, an OPNsense API key once Phase 2
lands, and the S3 credential for its own state backend
(`opentofu-state` on `storage` —
[`vm-provisioning.md`](../../vm-provisioning.md#state-backend--secrets)).
The doc's original text assumed these stay outside OpenBao entirely,
mirroring `openbao_utils/bootstrap.py`'s pre-OpenBao file-cache pattern —
but that mechanism no longer exists in this repo. Track A
([0013](../0013-credential-caching-stage-1-before-secrets-manager.md)
through
[0026](../0026-openbao-audit-device-and-r2-per-read-watcher.md))
retired it, and every other secret in this repo now lives in OpenBao
on `security`. The original reasoning for keeping Tofu's secrets
separate doesn't hold as stated anymore, but where they should live
instead hasn't been decided.

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
`Decided` before the very project it blocks was most of the way built.
The bootstrapping-order problem is therefore a **standing constraint**,
not a one-time migration-day concern — every future routine `security`
rebuild hits it again, not just the first one.

## Options

### A — Route through the existing OpenBao instance on `security`

Consistent with every other secret in this repo: one Vault, one
AppRole model, no new infrastructure. `controller` already holds an
AppRole and fetches secrets per run
([0020](../0020-controller-single-broad-approle-not-split-by-consumer.md));
extending that to Tofu's credentials needs no new mechanism.

Breaks whenever `security` itself is what's being (re)provisioned —
Tofu can't reach a secrets store that lives on the host it's trying to
build. Per the Context above, this isn't a one-time migration-day
edge case: it recurs every time `security` is rebuilt via Tofu going
forward, which weakens Option A more than the original framing
suggested.

### B — Keep genuinely separate (file-based, `.tfvars`)

No dependency on any host's state — Tofu can always run, even to
rebuild `security` from nothing. Matches the same reasoning behind
Ansible's own three permanent bootstrap exceptions (`main-domain`,
`openbao-controller-role-id`/`-secret-id`): Vault access itself
depends on them, so they can't live inside Vault.

Needs its own justification now rather than an inherited one — the
argument has to be the bootstrapping-order problem directly, not
"mirrors" a mechanism this repo no longer has.

### C — A dedicated Tofu/controller-scoped OpenBao instance

Solves A's bootstrapping problem (doesn't depend on `security`
existing) and gives Proxmox/OPNsense credentials their own trust tier
— Proxmox API access is a strictly higher blast radius (control of
every VM) than anything the main OpenBao currently holds.

Real cost: a second piece of standing infrastructure with its own
deploy, backup, and manual Shamir unseal
([0018](../0018-manual-shamir-unseal.md)) tied to whichever host runs
it. If that's `controller` (the operator's own machine, not
always-on), unseal availability follows the operator's laptop rather
than a dedicated server — a different story than `security`'s current
instance.

## Assumptions

- **Claim:** a second OpenBao instance (Option C) reduces risk rather
  than just relocating it.
  **Breaks if wrong:** if it ends up unsealed/backed up through the
  same access path as the main instance (same operator, same
  `storage` backup target), the isolation Option C is meant to buy
  doesn't materialize — it's extra infrastructure for no real benefit.
  **Checked by:** not resolvable by reading code — needs to be reasoned
  through explicitly if C is seriously pursued, covering who unseals
  it and whether its backup path is actually independent of the main
  instance's.
- **Claim:** the OPNsense API key needs the same treatment as the
  Proxmox token, on the same timeline.
  **Breaks if wrong:** the API key isn't needed until Stage 7, well
  after Stage 1 — Proxmox's token could resolve now under one option
  while the API key gets revisited separately once Phase 2 actually
  starts.
  **Checked by:** revisit once Stage 7 is actually being built, not
  before.

## Consequences

Whichever option is chosen shapes Stage 1's secrets-bootstrap script
and where the state-backend S3 credential itself lives — both are
blocked on this. Reversing a built choice later means migrating live
credentials (and possibly repointing Tofu's own state-backend auth),
not just editing a doc — this is a real decision, not a formality.
