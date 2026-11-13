---
id: PROJ-gcp-e2-micro-provisioning
title: GCP e2-micro Provisioning
type: project
status: not-started
blocked: false
summary: Onboard a GCP project and define the off-site e2-micro in OpenTofu, with a provisioning identity that leaves no standing key on the host.
decision: ADR-0073/0
plan: draft
super_project: off-site-monitoring
---

# GCP e2-micro Provisioning

Creates the part of the off-site relocation that does not exist yet: a
GCP project, a provisioning identity for it, and an OpenTofu definition
of the e2-micro that [`off-site-monitoring.md`](off-site-monitoring.md)
later configures and routes to. Staged because the module and its
state and inventory integration are separate reviewable changes.

## Scope

The GCP project, billing budget, provisioning identity, and the Tofu
module that creates one e2-micro and its network rules. Not in scope:
the monitoring stack and Tailscale route
([`off-site-monitoring.md`](off-site-monitoring.md)), the host hardening
pass ([ADR 0043 (Host hardening baseline)](../decisions/0043-host-os-hardening-baseline/revision-000.md)),
and credentials the host holds
([ADR 0047 (First-credential bootstrap)](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md)).

This project runs standalone. The module's layout follows Tofu's root module
([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#tofu-project)).
Its credentials follow
[ADR 0048 (Tofu credentials)](../decisions/0048-where-tofu-credentials-live/revision-000.md),
which keeps Tofu's credentials in a file on the Tofu host.

## Decision

Implements [ADR 0073 (Off-site cloud auth)](../decisions/0073-how-provisioning-authenticates-to-the-off-site-cloud/revision-000.md),
still `working`, so this project is `not-started` or `de-risking` until the revision is `approved`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Tofu module for the e2-micro, in this repo | Not started | a `tofu plan` of the module is clean against a free-tier GCP project, and an `apply` and `destroy` of the e2-micro show no charge on the billing view |
| 2 | State and inventory integration | Not started | state is kept as [`tofu/state-and-credentials.md`](../topics/infra/tofu/state-and-credentials.md) describes and the generated inventory includes the e2-micro |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] The e2-micro is defined in Tofu and created in a free-tier region with no charge on the billing view.
- [ ] The created host holds no credential to the GCP control plane.
- [ ] ADR 0073 is settled and no provisioning credential or state is in the repository.
- [ ] The resulting behavior is described in a topic doc, not only here.

## Agent handoff

- **Allowed to change:** documentation only until ADR 0073 is `approved`.
- **Must not change:** the Proxmox modules under `tofu/modules/` and the inventory generator in `tools/tofu_inventory/`, or any credential or state file in a commit.
- **Required checks:** `pre-commit run --all-files`.

## Risks

- A free-tier instance outside the three eligible US regions bills at the
  standard rate, and the allowance is by hours across the account, so a
  second instance bills even briefly.
- The module's directory layout may collide with the root module in
  `tofu/` ([`vm-provisioning.md`](../topics/infra/vm-provisioning.md#tofu-project)).
- The off-site monitor cannot be rebuilt if the GCP account's recovery
  factors are lost with the site; tracked as an assumption in ADR 0073.

## Open items

- Where the module lives in the repository relative to the root module in
  `tofu/`.
- Whether the free-tier instance's external address is billed. Google's
  free-tier page says it is not; confirm on the billing view.
- The instance's resident memory with Beszel and Gatus running, and its monthly egress, which [ADR 0049 (Site-loss monitoring)](../decisions/0049-monitoring-that-survives-loss-of-the-site/revision-000.md) leaves open.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
