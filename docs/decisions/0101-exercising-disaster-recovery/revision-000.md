---
id: ADR-0101
revision: 0
type: adr
title: Exercising disaster recovery often enough that it works when it is needed
short: DR exercise cadence
solution: A small set of exercise kinds on a cadence set by a recovery tier, with the tier derived from the catalog plus one flag for the systems every restore depends on, and results kept in a private record
summary: Which disaster-recovery exercises the repository runs, how often, and how the cadence follows from what a system's loss would cost, so the restore paths are exercised before they are needed.
topic: backup-recovery
status: approved
related: [ADR-0012, ADR-0111, ADR-0099, ADR-0100]
---

# 0101. Exercising disaster recovery often enough that it works when it is needed

## Problem

A backup, a bootstrap procedure and a rebuild runbook are only as good as the last
time anyone ran them. The repository has the means to exercise them and says
nothing about how often, on what, or in what order, so each exercise happens when
the maintainer remembers, and a path that is never chosen is never tested.

## Context

- **What exists.** A real fire drill restores one app on a scratch host. A restore
  drill rebuilds the secrets store from its snapshot
  ([ADR 0111 (Secrets store recovery)](../0111-recovering-the-secrets-store-from-total-loss/revision-000.md),
  [ADR 0099 (Rebuilding security from nothing)](../0099-rebuilding-security-from-nothing/revision-000.md)).
  A rebuild runbook destroys and recreates a host from the repository and its
  backups. Automated checks prove that backups land
  ([ADR 0012 (Backup verification)](../0012-verifying-backups-actually-land/revision-000.md)).
  The maintainer's drill record keeps each real restore, with its source, privately.
- **No cadence is stated anywhere.** None of those documents or decisions says how
  often a drill runs, which apps it covers in turn, or when a cloud copy rather than
  the on-site one is the source.
- **Established practice.** NIST SP 800-34 asks for a yearly tabletop exercise for a
  low-impact system, a yearly functional exercise that includes a restore from
  backup for a moderate one, and a yearly full-scale exercise for a high-impact one;
  its control CP-4 sets the frequency at no less than yearly
  ([NIST CP-4](https://opensecurityarchitecture.org/controls/cp-04)). AWS Well-Architected
  asks for backups to be restored periodically to a new location and checked
  ([REL09-BP04](https://docs.aws.amazon.com/wellarchitected/latest/framework/rel_backing_up_data_periodic_recovery_testing_data.html)),
  and says the recovery path tested often is the one that works
  ([REL13-BP03](https://docs.aws.amazon.com/wellarchitected/latest/framework/rel_planning_for_recovery_dr_tested.html)).
  Google starts with small, service-specific drills and role-plays past incidents.
  This record borrows their shape and claims conformance with none.
- **What the loss of a system costs differs.** Every other restore needs the secrets
  store, the certificate authority, the storage host and the offline key. Another
  app's restore needs only those. An app with no backup is rebuilt by deploying it.
- **The tier cannot be read from `backup` alone.** OpenBao and SeaweedFS, the two
  systems every restore depends on, have no `backup` entry: the secrets store is
  backed up by its own snapshot, and SeaweedFS is the backup target. A tier derived
  only from `backup` would put them last.
- **Capacity is one maintainer and one node.** The rebuilt hosts' sizes in
  [`main.tf`](../../../tofu/main.tf) add up to 14 GB of RAM,
  and the live hosts use the same again, on a node with 32 GB. The estate cannot be
  rebuilt twice at once.
- **The results are private.** How the exercises were run and what they found is
  kept out of this repository
  ([`data-classification.md`](../../topics/engineering/data-classification.md)).
  [ADR 0100 (Recording a system's integration)](../0100-recording-how-a-system-is-integrated/revision-001.md)
  shows each system's tier in the coverage view, and a check kept with the private
  record reports the age of each system's newest restoring drill against this cadence.

## Decision

**Recovery tiers.** A system's tier sets how often it is exercised.

| Tier | Which systems | How it is set |
| :--- | :--- | :--- |
| 1 | Every other restore depends on it: the secrets store, the certificate authority, the storage host, and custody of the offline key | A `recovery_tier: 1` key on its `app_catalog` entry; the key custody is an exercise of its own, below |
| 2 | Any other app with a `backup` entry | Derived from the catalog |
| 3 | An app with no backup | Derived from the catalog |

The coverage view shows each system's tier, so no list of systems is kept in prose,
and `check-app-catalog` refuses a `recovery_tier` other than `1`.

**Exercises and cadence.**

| Exercise | Kind | Scope | Cadence |
| :--- | :--- | :--- | :--- |
| Backup check | automated | Every backed-up app has a recent archive on some source | Continuous, and before each rebuild |
| App restore | functional | One app restored on a scratch host and compared with its archive | Monthly, rotating, so each tier 2 system is restored once a year and each tier 1 system twice |
| Cloud-source restore | functional | An app restore whose source is a cloud copy, not the on-site one | At least one a quarter |
| Host rebuild | functional | One host destroyed and recreated from the repository and its backups | One every two to three months, each host within twelve |
| Key custody | functional | The offline key, the unseal shares and the break-glass credentials are retrieved and used to decrypt a real archive | Yearly, and after any rotation |
| Tabletop | tabletop | One scenario from a short list kept in the exercise doc | Twice a year |
| Total loss | full-scale, staged | The secrets-store bootstrap, then storage, then one app host, from the cloud copies alone, in the isolated block | Once after the host migration, then every two years, or yearly once capacity allows |
| Re-test | functional | The component that a material change touched | When it happens |

A material change is a new backed-up app, a change to the backup or restore roles,
an upgrade of the secrets store or the authority, and a change of the authority's root.

**When the cadence cannot be kept.** If the staged total-loss exercise does not fit in
the isolated block, it is run as a tabletop of the same chain until it does, and the
private record says so. A monthly restore that is missed is carried to the next month,
not skipped; a cadence missed for two quarters running is a reason to revise this record,
not to ignore it.

**Records.** Each real restore or rebuild is an entry in the private drill record, with its
source. A tabletop, a custody check and a total-loss exercise add an entry too, saying
what was done and what it found, as a change to the procedure or the records and
never as a security incident.

**Review.** The recurring operational readiness review of ADR 0100 reads the
private record's ages against this cadence. How it reports a late exercise is not
decided here.

## Alternatives considered

- **One large exercise a year, as Google's company-wide DiRT does.** It exercises the
  whole chain, and a single maintainer would run it late or skip it, and gets one
  data point a year per path. Lost on cost.
- **A cadence per app in the catalog (`drill_every`).** Flexible, and every value is
  one more number to drift. Three tiers and a rotation cover the same ground.
- **Deriving tier 1 from `backup` and the host.** It misses the two systems named
  above and would encode their names in the generator instead of in the catalog.
- **Scheduled automated restores into a scratch host.** The usual answer in the cloud
  guidance. It needs a scratch host that can be created unattended, which does not
  exist here. Revisit once the migration is done.

## Consequences

- The coverage view gains a tier column, and `app_catalog` gains one optional key. The ages of drills are not in it.
- An exercise doc under `docs/topics/disaster-recovery/` holds the procedures, the
  tabletop scenarios and the rule for each tier. It names no system.
- The host migration counts as the first cycle of host rebuilds.
- Exercises cost time every month. That is the price of knowing the paths work.

## Invariants

- Every real restore or rebuild leaves an entry in the private drill record.
- A tier 1 system is never exercised less often than the tier 2 cadence.
- The tier of a system comes from the catalog, never from a list in prose.

## Non-goals

- Recovery time and data-loss targets. Each system's record states its own
  ([ADR 0100](../0100-recording-how-a-system-is-integrated/revision-000.md)).
- Exercising the loss of the gateway or the network boundary, which has its own project.
- Automating the exercises.
- Scoring or grading an exercise.

## Validation

`check-app-catalog` for the `recovery_tier` key; the coverage view for each system's
tier; the private drill record for what was done and each system's newest restoring drill.

## Reconsideration triggers

An exercise finds a failure that no earlier one would have, a tier 2 system turns out to
be a restore dependency, or the cadence is missed for two quarters running.
