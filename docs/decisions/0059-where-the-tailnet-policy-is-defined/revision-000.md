---
id: ADR-0059
revision: 0
type: adr
title: Where the tailnet policy is defined
solution: Hand-edited in the console now, with tests as the guard; moves to OpenTofu via the tailscale/tailscale provider once ADR 0048 settles where Tofu's own credentials live
summary: The tailnet ACL policy is a security boundary ADRs 0049, 0053, and 0058 depend on; decide where it is authored and when that changes.
topic: security-hardening
status: working
related: [ADR-0015, ADR-0048, ADR-0049, ADR-0053, ADR-0058]
---

# 0059. Where the tailnet policy is defined

## Problem

The tailnet's ACL policy — what any node is allowed to reach — is a
security boundary that ADR 0049's off-site hop, ADR 0053's coding-agent
isolation, and ADR 0058's operator-host access all depend on. Decide
where it is authored, reviewed, and changed, and whether that changes
over time.

## Context

The policy today is the default allow-all grant, held only in the
Tailscale admin console ([`network-infra.md`](../../network-infra.md);
recorded in ADR 0058's Context). No revision of it has ever been
reviewed as code. ADR 0058's Stage 2
([`operator-host.md`](../../projects/operator-host.md)) is about to
hand-edit it for the first time, replacing allow-all with explicit
grants for VLAN 30.

Managing the policy as OpenTofu is a candidate for the same or a later
stage. Tailscale publishes its own provider (`tailscale/tailscale`),
which manages the whole policy file through `tailscale_acl` and
per-device subnet-route approval through
`tailscale_device_subnet_routes`. It is listed on the OpenTofu registry
(`search.opentofu.org/provider/tailscale/tailscale`), so `tofu init`
can resolve it; whether the registry ever received the provider's GPG
signing key — the subject of a 2024 upstream feature request — is not
confirmed (see Assumptions).

Coding it now, rather than after the first hand-edit, has four costs:

- **A new credential.** Applying the policy needs an API credential
  able to rewrite the tailnet's isolation boundary. Tailscale
  recommends against committing it, so it belongs with the operator
  host's credentials — another entry in ADR 0048's still-`working`
  question of where Tofu's own credentials live.
- **Expiry.** Tailscale recommends an OAuth or federated credential for
  this because it is tied to the tailnet rather than a user and does
  not expire on its own. ADR 0015's principle is that every credential
  expires and something notices; a standing OAuth credential either
  needs an exception or a rotation scheme layered on top.
- **Lockout.** Tofu applying this policy would run from the operator
  host, which ADR 0058 makes reachable only through the policy itself.
  A bad apply can cut off the host that would fix it. The console
  remains break-glass, and the `tests` block ADR 0058's Stage 2
  already requires is what catches a bad apply before it saves.
- **Public repo.** The policy file contains the maintainer's email and
  device IPs. Committing it means a template with the private values
  supplied from outside — the same pattern `main-domain` already uses.

## Decision

Hand-edit the policy in the console now, for ADR 0058's Stage 2,
guarded by a copy of the prior policy and the console's own preview
before saving, as `operator-host.md` Stage 2 already specifies.

Move it into OpenTofu once ADR 0048 is `accepted` and settles where
Tofu's own credentials live: the `tailscale/tailscale` provider, an
OAuth-client credential stored wherever ADR 0048 lands, `tailscale_acl`
for the policy body, and `tailscale_device_subnet_routes` plus
auto-approvers in the policy for route approval. This repo does not
otherwise manage devices, keys, or DNS through this provider (see
Alternatives). The template lives in this repo; the maintainer's email
and device IPs are supplied at apply time the way `main-domain` is.

## Alternatives considered

- **Code it now, ahead of ADR 0048.** Forces a credential-storage
  decision under this ADR that ADR 0048 already owns, and stands up a
  standing OAuth credential before ADR 0015's expiry principle has an
  answer for it. Rejected.
- **Never code it.** Leaves the security boundary three other ADRs
  depend on with no review history or drift detection. Rejected.
- **Manage devices and DNS through the same provider.** Auth keys would
  sit in Tofu state for no benefit this tailnet's size needs, and the
  one useful piece — route approval — is already covered by
  auto-approvers in the policy. Rejected.

## Assumptions

- **Claim:** the `tailscale/tailscale` provider is installable through
  `tofu init` with signature verification, not just listed in the
  registry index.
  **Breaks if wrong:** `tofu init` still reports skipped signature
  validation, meaning the 2024 GPG-key request was never resolved;
  Tofu-managed policy would ship without provider-signature
  verification unless a mirror or manual key trust is added.
  **Checked by:** a throwaway `tofu init` spike against a scratch
  config requiring `tailscale/tailscale`, checked for a
  signature-skipped warning.

## Consequences

- The policy stays a manual, console-only artifact through ADR 0058's
  Stage 2, with no drift detection until this ADR reaches `accepted`
  and its implementation lands.
- Once coded, the policy joins ADR 0048's credential-storage answer and
  its rotation/expiry cadence, rather than getting a bespoke one.
- A wrong Tofu apply can still lock out the operator host after this
  lands; the console and the `tests` block remain the recovery path,
  not a Tofu rollback.

## Invariants

- The policy's live, authoritative copy always has a corresponding
  backup taken before any change, hand-edited or applied.
- No apply of this policy runs from a host reachable only through the
  route the apply could remove, without the console as an independent
  recovery path.

## Non-goals

- Managing individual devices, auth keys, or DNS records through this
  provider (see Alternatives).
- Resolving ADR 0048 itself.

## Validation

Once implemented: a `tofu plan` against the live policy after a manual
console change reports drift; a deliberately locking `tests` entry
fails the apply before it saves.

## Reconsideration triggers

- ADR 0048 lands on a credential store this provider's OAuth client
  can't use as-is.
- The registry's signing-key gap turns out to still be open, and no
  acceptable mirror or key-trust workaround exists.
