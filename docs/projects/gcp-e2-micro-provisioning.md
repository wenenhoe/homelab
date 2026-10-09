---
id: PROJ-gcp-e2-micro-provisioning
title: GCP e2-micro Provisioning
type: project
status: de-risking
blocked: false
summary: Onboard a GCP project and define the off-site e2-micro in OpenTofu, with a provisioning identity that leaves no standing key on the host.
decision: ADR-0073/0
super_project: off-site-monitoring
track: monitoring
phase: 2-off-site
---

# GCP e2-micro Provisioning

Creates the part of the off-site relocation that does not exist yet: a
GCP project, a provisioning identity for it, and an OpenTofu definition
of the e2-micro that [`off-site-monitoring.md`](off-site-monitoring.md)
later configures and routes to. Staged because the identity question
([ADR 0073 (Off-site cloud auth)](../decisions/0073-how-provisioning-authenticates-to-the-off-site-cloud/revision-000.md))
has to be answered by a throwaway spike before any Tofu code for it
lands in this repo.

## Scope

The GCP project, billing budget, provisioning identity, and the Tofu
module that creates one e2-micro and its network rules. Not in scope:
the monitoring stack and Tailscale route
([`off-site-monitoring.md`](off-site-monitoring.md)), the host hardening
pass ([ADR 0043 (Host hardening baseline)](../decisions/0043-host-os-hardening-baseline/revision-000.md)),
and credentials the host holds
([ADR 0047 (First-credential bootstrap)](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md)).

This project runs standalone. It does not depend on
[`tofu-vm-provisioning.md`](tofu-vm-provisioning.md): its spike uses
local state, and the in-repo layout and state backend follow
[ADR 0048 (Tofu credentials)](../decisions/0048-where-tofu-credentials-live/revision-000.md)
once that settles.

## Decision

Implements [ADR 0073 (Off-site cloud auth)](../decisions/0073-how-provisioning-authenticates-to-the-off-site-cloud/revision-000.md),
still `working`, so this project is `de-risking` and only throwaway
spikes are allowed until its assumptions are resolved.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike: GCP project, budget alert, and a Tofu identity, with local state outside the checkout | Not started | an e2-micro in a free-tier region is created and destroyed by `tofu apply` and `tofu destroy`, each ADR 0073 assumption is recorded as a fact in the ADR, and the billing view shows no charge |
| 2 | Tofu module for the e2-micro, in this repo | Not started | ADR 0073 is `approved` and a `tofu plan` of the module is clean against the spike project |
| 3 | State and inventory integration | Not started | state lives where ADR 0048 decides and the generated inventory includes the e2-micro |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — Spike

The spike's code, state, and any credential live outside the repository
checkout and are deleted afterwards; only facts go back into
[ADR 0073 (Off-site cloud auth)](../decisions/0073-how-provisioning-authenticates-to-the-off-site-cloud/revision-000.md)
and [ADR 0049 (Site-loss monitoring)](../decisions/0049-monitoring-that-survives-loss-of-the-site/revision-000.md).
It also measures what ADR 0049 leaves open: the instance's resident
memory with Beszel and Kuma running, and monthly egress.

## Acceptance criteria

- [ ] The e2-micro is defined in Tofu and created in a free-tier region with no charge on the billing view.
- [ ] The created host holds no credential to the GCP control plane.
- [ ] ADR 0073 is settled and no provisioning credential or state is in the repository.
- [ ] The resulting behavior is described in a topic doc, not only here.

## Agent handoff

- **Allowed to change:** documentation only until ADR 0073 is `approved`; Stage 1 produces nothing in the repository.
- **Must not change:** [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md)'s files, or any credential or state file in a commit.
- **Required checks:** `pre-commit run --all-files`.

## Risks

- A free-tier instance outside the three eligible US regions bills at the
  standard rate, and the allowance is by hours across the account, so a
  second instance bills even briefly.
- The module's directory layout may collide with the layout
  [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md) sets in its Stage 1.
- The off-site monitor cannot be rebuilt if the GCP account's recovery
  factors are lost with the site; tracked as an assumption in ADR 0073.

## Open items

- Where the module lives in the repository: decided with
  [`tofu-vm-provisioning.md`](tofu-vm-provisioning.md)'s skeleton, not before.
- Whether the free-tier instance's external address is billed. Google's
  free-tier page says it is not; confirm on the spike's billing view.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
