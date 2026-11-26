# Disaster-recovery exercises

A backup, a bootstrap procedure and a rebuild runbook are only known to work from the
last time someone ran them. This page says which exercises are run, how often, in what
order, and where each is recorded. The decision is
[ADR 0101 (DR exercise cadence)](../../decisions/0101-exercising-disaster-recovery/revision-000.md).
The procedures it points at are [`restore.md`](restore.md), [`fire-drill.md`](fire-drill.md),
[`rebuild-runbook.md`](rebuild-runbook.md) and
[`backup-restore.md`](../security/openbao/backup-restore.md). The exercise kinds follow
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

**Backup check.** Lists the newest archive of each app on every source and its age, and restores
nothing ([what it checks](rebuild-tools.md#what-the-checks-look-at)). From the repo root:

```sh
python3 ansible/scripts/restore_all.py --check
```

**App restore.** The real fire drill in [`fire-drill.md`](fire-drill.md#real-fire-drill), on a scratch
host. Pick the system whose newest restoring drill in the private drill record is oldest, and a
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

**Key custody.** Retrieve from where they are kept the offline private key, the break-glass
read-only credential, the Tofu state encryption passphrase and the unseal shares, and count the
shares. Then use all but the shares, which are used in the restore drill and in the total-loss
exercise:

| Item | Proven by |
| :--- | :--- |
| Offline private key | Decrypting a real app archive ([`restore.md`](restore.md#manual-steps-first)) |
| Break-glass read-only credential | Pulling and decrypting the latest secrets-store snapshot, as below |
| Backup key, for the state copy | Decrypting the newest object under `state/` in the state copy bucket ([State copy](../infra/tofu/state-and-credentials.md#state-copy)) |
| State encryption passphrase | The offline copy and the one in use have the same SHA-256, as below |

```sh
# from the repo root; asks for the credential and the key's passphrase, writes ~/restore.snap
tools/openbao_utils/scripts/snapshot-pull.sh r2 ~/restore.snap
```

([What it asks for](../security/openbao/backup-restore.md#pulling-a-snapshot).) Compare the
passphrase without printing either copy:

```sh
# paste alone; it waits for the offline passphrase, hidden
read -rs -p 'offline passphrase: ' offline; echo
```

```sh
# paste alone; it waits for the passphrase in use, hidden
read -rs -p 'passphrase in use: ' live; echo
```

```sh
[ "$(printf %s "$offline" | sha256sum)" = "$(printf %s "$live" | sha256sum)" ] && echo match || echo DIFFERENT
unset offline live
```

Delete every decrypted file afterwards.

**Tabletop.** Take the next scenario from the list, state it in a sentence, walk the runbooks as
if it had happened, and write down what is missing or wrong. The scenarios are the loss of the
development VM and the credentials file it holds, the loss of the storage host together with one cloud copy,
a compromised app host (the adversary [`backup-threat-model.md`](backup-threat-model.md) assumes),
and the loss of the workstation that holds the break-glass credentials. Each is walked once in
two years.

**Total loss.** In the isolated block, with no on-site copy, each from the cloud copies: the
secrets-store bootstrap
([`backup-restore.md`](../security/openbao/backup-restore.md#rebuilding-security)), then the
storage host, then one app host. It is staged because the node cannot hold the estate twice at
once. If the chain does not fit in the isolated block, it is walked as a tabletop until it does,
and the drill record says so.

**Re-test.** The part of the above that the change touched:

| Change | Re-test |
| :--- | :--- |
| A new backed-up app | An app restore |
| The backup or restore roles | One app restore on each tier |
| An upgrade of the secrets store or the authority | The bootstrap path |
| A new root | A host rebuild, since every host's trust is involved |

## Recording

Every real restore or rebuild is an entry in the private drill record, with its source. A tabletop, a
key-custody check and a total-loss exercise add an entry too, saying what was done and what was found.
What a tabletop finds is written as a change to a procedure or a record, never as a security incident or an
exposure ([`docs/README.md#public-repo`](../../README.md#public-repo)). The results are not kept here
([`data-classification.md`](../security/policy/data-classification.md)); a check that reads the record against
the cadence above reports a system or an exercise that is late.

## When the cadence cannot be kept

A monthly restore that is missed is carried to the next month, not skipped. A cadence missed for
two quarters running is a reason to revise
[ADR 0101](../../decisions/0101-exercising-disaster-recovery/revision-000.md), not to ignore it.
