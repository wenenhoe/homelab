# Disaster-recovery exercises

A backup, a bootstrap procedure and a rebuild runbook are only known to work from the
last time someone ran them. This page says which exercises are run, how often, in what
order, and where each is recorded. The decision is
[ADR 0101 (DR exercise cadence)](../../decisions/0101-exercising-disaster-recovery/revision-000.md).
The procedures it points at are [`restore.md`](restore.md), [`fire-drill.md`](fire-drill.md),
[`rebuild-runbook.md`](rebuild-runbook.md) and
[`openbao-backup-restore.md`](../secrets/openbao-backup-restore.md). The exercise kinds follow
NIST SP 800-34's tabletop, functional and full-scale exercises; this page claims conformance
with no standard.

## Recovery tiers

A system's tier sets how often it is exercised. No system is listed here: the tier comes from
[`app_catalog.yaml`](../../../ansible/inventory/group_vars/all/app_catalog.yaml).

| Tier | Which systems | How it is set |
| :--- | :--- | :--- |
| 1 | Every other restore depends on it | `recovery_tier: 1` on its catalog entry ([`adding-an-app.md`](../deploy/adding-an-app.md)) |
| 2 | Any other app with a `backup` entry | Derived: it has a `backup` |
| 3 | An app with no backup, rebuilt by deploying it | Derived: it has none |

A tier 1 system is exercised at least as often as a tier 2 one.

## The exercises

| Exercise | Kind | What it proves | Cadence |
| :--- | :--- | :--- | :--- |
| Backup check | automated | Every backed-up app has a recent archive on some source | Continuous, and before each rebuild |
| App restore | functional | An archive decrypts and an app comes back from it | Monthly, rotating: each tier 2 system once a year, each tier 1 system twice |
| Cloud-source restore | functional | The off-site copy, its read credential and the offline key work without the on-site copy | At least one a quarter |
| Host rebuild | functional | A host returns from the repository and its backups | One every two to three months; each host within twelve |
| Key custody | functional | The offline key, the unseal shares and the break-glass credentials can be retrieved and used | Yearly, and after any rotation |
| Tabletop | tabletop | The runbooks cover a scenario nobody has lived | Twice a year |
| Total loss | full-scale, staged | Everything returns from the cloud copies alone | Once after the host migration, then every two years, or yearly once capacity allows |
| Re-test | functional | A change did not break the path it touched | When it happens |

A change is material when it adds a backed-up app, changes the backup or restore roles, upgrades
the secrets store or the certificate authority, or changes the authority's root.

## How each is run

**Backup check.** `python3 ansible/scripts/restore_all.py --check` lists the newest archive of
each app on every source and its age, and restores nothing
([`rebuild-tools.md`](rebuild-tools.md#what-the-checks-look-at)).

**App restore.** The real fire drill in [`fire-drill.md`](fire-drill.md#real-fire-drill), on a scratch
host. Pick the system whose newest row in the [results](fire-drill.md#results) is oldest, and a
tier 1 system when two are level. Compare the restored data with the archive, not only the
exit status.

**Cloud-source restore.** `restore_all.py` reads the on-site copy first and turns to a cloud
target only when that is unreachable or empty, so this exercise takes the object from the
cloud itself, as [`restore.md`](restore.md#manual-steps-first) describes for a lost storage host,
and restores it with the per-app playbook. Rotate the provider between exercises, and include the
large app whose copy goes to the provider with a delete-after window
([`cloud-sync.md`](cloud-sync.md#oci-window)).

**Host rebuild.** [`rebuild-runbook.md`](rebuild-runbook.md), for the host rebuilt longest ago.
The host migration's rebuilds count as the first cycle.

**Key custody.** Retrieve the offline private key, the break-glass read-only credential and the
unseal shares from where they are kept, and count the shares. Then use the key and the credential:
decrypt a real app archive ([`backup.md`](backup.md#encryption)) and pull and decrypt the latest
secrets-store snapshot with
[`snapshot-pull.sh`](../secrets/openbao-backup-restore.md#pulling-a-snapshot). The shares are used in
the restore drill and in the total-loss exercise, not here. Delete every decrypted file afterwards.

**Tabletop.** Take the next scenario from the list, state it in a sentence, walk the runbooks as
if it had happened, and write down what is missing or wrong. The scenarios are the loss of the
development VM and the state it holds, the loss of the storage host together with one cloud copy,
a compromised app host (the adversary [`backup-threat-model.md`](backup-threat-model.md) assumes),
and the loss of the workstation that holds the break-glass credentials. Each is walked once in
two years.

**Total loss.** In the isolated block, with no on-site copy: the secrets-store bootstrap
([`openbao-backup-restore.md`](../secrets/openbao-backup-restore.md#rebuilding-security)), then the
storage host, then one app host, each from the cloud copies. It is staged because the node cannot
hold the estate twice at once. If the chain does not fit in the isolated block, it is walked as a
tabletop until it does, and the results row says so.

**Re-test.** The part of the above that the change touched: a new backed-up app gets an app restore;
a change to the backup or restore roles gets one on each tier; an upgrade of the secrets store or
the authority gets the bootstrap path; a new root gets a host rebuild, since every host's trust is involved.

## Recording

Every real restore or rebuild is a row in the fire-drill [results](fire-drill.md#results), with
its source. A tabletop, a key-custody check and a total-loss exercise add a row too, saying what
was done and what was found. What a tabletop finds is written as a change to a procedure or a
record, never as a security incident or an exposure
([`docs/README.md#public-repo`](../../README.md#public-repo)).

## When the cadence cannot be kept

A monthly restore that is missed is carried to the next month, not skipped. A cadence missed for
two quarters running is a reason to revise
[ADR 0101](../../decisions/0101-exercising-disaster-recovery/revision-000.md), not to ignore it.
