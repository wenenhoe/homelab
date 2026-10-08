---
id: ADR-0073
revision: 0
type: adr
title: How provisioning authenticates to the off-site cloud account
short: Off-site cloud auth
solution: 'Undecided: a service-account key, service-account impersonation, or workload identity federation'
summary: How Tofu proves itself to the GCP account that hosts the off-site monitor, without a standing credential that outlives its use or reaches the host it creates.
topic: cloud-credentials
status: working
related: [ADR-0015, ADR-0047, ADR-0048, ADR-0049, ADR-0056, ADR-0058]
---

# 0073. How provisioning authenticates to the off-site cloud account

## Problem

Tofu has to create and change the off-site monitor's VM and network rules
in a cloud account this lab does not own the hardware of. That needs a
credential to the account. The credential has to be narrow, has to
expire or never exist as a file, and must not be the same thing the
created host holds.

## Context

[ADR 0049](../0049-monitoring-that-survives-loss-of-the-site/revision-000.md)
places the off-site monitor on a GCP e2-micro. Nothing in this repo
reaches GCP yet: `tools/cloud_credentials` covers B2, R2, and OCI only,
and those modules mint backup leaf keys, not a provisioning identity.

Two credentials are in play and only one is this record's:

- **Provisioning credential** (this record): what Tofu uses to call the
  GCP API.
- **Credentials the host holds** (Beszel's KEY/TOKEN, Telegram wiring,
  Kuma state): [ADR 0047](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md).

[ADR 0048](../0048-where-tofu-credentials-live/revision-000.md) decides
where Tofu's Proxmox, OPNsense, and state-backend credentials live. Its
open fork is the bootstrap-order problem of rebuilding `security`, which
does not apply here: nothing in GCP hosts the secrets store. What it
shares with this record is the question of which machine holds a
standing infrastructure credential, answered for the maintainer side by
[ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md)
and [ADR 0058](../0058-where-operator-work-runs/revision-000.md).

**Threat model.** Asset: the GCP project, and through it the off-site
host, which holds a live route back to the managed hosts over the
tailnet. Adversary: whoever obtains the provisioning credential. Attack
path: use it to change the host's metadata, firewall rules, or boot
image, then act from a host the lab cannot physically secure. A key
file that never expires and sits on a workstation is the weakest
version of this path; a credential that is minted per run and held by
nothing at rest is the strongest.

## Decision

Not yet. The options below are the candidates; none is chosen. The
spike in [`gcp-e2-micro-provisioning.md`](../../projects/gcp-e2-micro-provisioning.md)
exists to turn the assumptions into facts.

## Alternatives considered

### A — Service-account key file

One JSON key for a service account scoped to the project's Compute
Engine and network resources. Simplest to wire into Tofu, and the
pattern most Tofu-on-GCP examples use. A file at rest that does not
expire by itself.

### B — Service-account impersonation

The operator's own Google identity signs in interactively and obtains
short-lived tokens for the scoped service account; no key file exists
anywhere. Moves the standing credential to the operator identity, which
then belongs on the operator host per ADR 0056 and ADR 0058.

### C — Workload identity federation

Tofu presents a token from an identity provider the project trusts, in
exchange for short-lived access. No standing secret on the Tofu side at
all, at the cost of running or borrowing an issuer GCP can verify.

## Assumptions

- **Claim:** the provider's service-account impersonation setting works
  for creating and destroying a Compute Engine instance with the
  operator identity holding only the permission to impersonate.
  **Breaks if wrong:** Option B collapses to A or C.
  **Checked by:** the Stage 1 spike in
  [`gcp-e2-micro-provisioning.md`](../../projects/gcp-e2-micro-provisioning.md).
- **Claim:** an account without a Google Cloud organization can still
  limit a service-account key's lifetime.
  **Breaks if wrong:** Option A has no native expiry, and ADR 0015's
  self-tracking pattern would have to be extended to a fourth provider.
  **Checked by:** reading Google's documentation for the org policy
  that governs key lifetime, then attempting it in the spike project.
- **Claim:** an issuer GCP can trust for Option C exists in this lab.
  **Breaks if wrong:** Option C needs new standing infrastructure.
  **Checked by:** reading what the existing identity components can
  issue; not yet done.
- **Claim:** the identity that owns the GCP account and its billing is
  recoverable after loss of the site.
  **Breaks if wrong:** the off-site monitor cannot be rebuilt in the
  scenario [ADR 0049](../0049-monitoring-that-survives-loss-of-the-site/revision-000.md)
  exists for.
  **Checked by:** naming where the account's recovery factors live
  before this revision is approved.

## Consequences

Stage 2 of the project cannot be built in this repo until this revision
is `approved`. Whichever option wins changes what
[ADR 0048](../0048-where-tofu-credentials-live/revision-000.md)'s
Option A, B, or C has to hold for Tofu alongside the GCP identity.

## Invariants

- The host Tofu creates holds no credential to the GCP control plane.
- No provisioning credential or Tofu state is committed to this
  repository.

## Non-goals

- Credentials the monitoring host itself holds
  ([ADR 0047](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md)).
- Hardening the created host
  ([ADR 0043](../0043-host-os-hardening-baseline/revision-000.md)).
- Where Tofu state is stored after the spike
  ([ADR 0048](../0048-where-tofu-credentials-live/revision-000.md)).
