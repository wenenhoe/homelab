---
id: ADR-0068
revision: 0
type: adr
title: "Where per-app backup settings get their defaults"
short: Backup defaults
solution: "A pure backup_plan filter over resolved_apps and one backup_defaults block whose keys match an app's backup block; roles read backup_plan, and the backup hosts are derived from it"
summary: "Where an app's backup settings meet the shared defaults, what decides that an app is backed up, and what those settings and the hosts that run them are called."
topic: backup-recovery
status: accepted
related: [ADR-0006, ADR-0012, ADR-0065]
---

# 0068. Where per-app backup settings get their defaults

## Problem

An app's backup settings (what to back up, when, how long to keep it, whether to stop it, which clouds receive a copy) have a value per app in the catalog and a shared default everywhere else. Every role that acts on backups needs the combination, and the decision that an app is backed up at all. Both must be made in one place, be readable for any host's apps regardless of which plays have run, be testable without Docker, and be named so that a default and the setting it defaults read as the same thing.

## Context

- `backup_agent` (`tasks/build_schedules.yaml`) fills in `stop_during_backup`, `retention_days`, `cron` and `compression` for each app. `retention_days` and `cron` fall back to variables in `group_vars/all`; `compression` and `stop_during_backup` fall back to literals in the task.
- `cloud_sync` and `restore_discovery` each spell out the same fallback for `backup.extra_cloud_targets`, in their own Jinja. The default, `cloud_sync_default_targets`, is defined in `host_vars/storage.yaml`, next to `cloud_sync_targets`, the definitions of each target including its write credentials. `restore_discovery` runs on the controller and reads the default through `hostvars['storage']`. A comment there says a change to either copy "stays in sync automatically", but the two are hand-written expressions: only the default's value is shared, not the logic that applies it.
- An app that sets `extra_cloud_targets` replaces the default; it does not add to it. The value can be the default's own contents, so "extra" does not describe it.
- Whether an app is backed up is tested three ways: `app.backup is defined` in `cloud_sync`, and `(backup.volumes | default([])) | length > 0` in `restore_discovery` and `backup_agent`. All eight apps that have a `backup:` block have non-empty `backup.volumes`, so the three agree today. Nothing enforces it: a `backup:` block with no volumes would get cloud-sync jobs for a path `backup_agent` never writes, and be absent from the restore manifest.
- Nothing checks that each name in `extra_cloud_targets` exists in `cloud_sync_targets`. A misspelling fails at deploy time with an undefined-variable error.
- `offsite_backup_s3_bucket`, `offsite_backup_s3_endpoint` and `offsite_backup_s3_proto` locate the SeaweedFS bucket that `backup_agent` uploads into and `cloud_sync` reads from. The endpoint is `s3.` plus `storage`'s `caddy_domain`. The cloud copies are what is offsite; these are not.
- `offsite_backup_freshness_buffer_hours` is slack added to an app's cron-derived interval before the freshness check stops pushing to Kuma. The check looks at the objects that have landed in SeaweedFS ([ADR 0012](../0012-verifying-backups-actually-land/revision-000.md)).
- `seaweedfs_backup_hosts` (`host_vars/storage.yaml`) is a hand-maintained list of the hosts that back up. It is read by the SeaweedFS identity template and by `cloud_sync`'s job loop. Each entry also needs a secret pair in `secret_catalog.yaml` and the host's own `seaweedfs_s3_access_key` and `seaweedfs_s3_secret_key`. `backup_agent` already skips a host with no backup volumes, so the list equals the managed hosts that have at least one backed-up app: `services` (two), `security` (five) and `play` (one) today, and `storage` none.
- `resolved_apps` ([ADR 0065](../0065-where-app-defaults-and-host-intent-are-merged/revision-000.md)) is a lazy `group_vars/all` variable readable for any host through `hostvars`, and a filter plugin in `ansible/filter_plugins/` is plain Python with a pytest suite. `cron_period_hours` and `resolve_apps` are the existing examples.
- Defined in `group_vars/all`, `backup_plan` and a host list derived from it evaluate to the same value from a controller-only play and from `storage`'s play. The filter receives Ansible's lazily templated list and mapping types, and reads them as a `Sequence` and a `Mapping`. A filter that takes `hostvars` and the host names directly gives the same list as a longer Jinja expression that builds a host-to-plan mapping first.
- Derived from `managed_hosts` in inventory order, the backup hosts are `services`, `play` and `security`: the same set as `seaweedfs_backup_hosts`, with `play` and `security` in the opposite order. Rendered with either list, the SeaweedFS identity file has identical entries; only that order differs.
- The `seaweedfs` app's identity file is a seeded config. A change to its rendered content marks the `data` volume changed, and the app is restarted.
- `cloud_sync_targets` holds credentials rendered from `secrets_generated`, which is why it lives with the host that uses them ([ADR 0006](../0006-offsite-backup-credential-blast-radius/revision-000.md)). The default is only a list of target names.

## Decision

- Shared defaults for backup settings live in one mapping, `backup_defaults`, in `group_vars/all`. Its keys are the keys of an app's `backup:` block: `cron`, `retention_days`, `compression`, `stop_during_backup` and `cloud_targets`. It replaces `offsite_backup_cron`, `offsite_backup_retention_days`, the literals in `backup_agent`, and `cloud_sync_default_targets`. The values do not change.
- The catalog key `backup.extra_cloud_targets` is renamed `backup.cloud_targets`. An app's list replaces the default, as it does now.
- `cloud_sync_targets` stays a `storage` host variable. Only target names move.
- A filter `backup_plan(resolved_apps, backup_defaults)` returns one entry per backed-up app, each with every setting resolved. It is pure: no file, network or Ansible-state access. A list value replaces the default; nothing is merged inside it. It is the only place that decides an app is backed up, which it does when `backup.volumes` is non-empty, and the only place a backup default is applied.
- `backup_plan` is defined once in `group_vars/all` as `"{{ resolved_apps | backup_plan(backup_defaults) }}"`, so any host's value is reachable through `hostvars`. A Molecule scenario that does not load `group_vars/all` sets `backup_plan` and `backup_hosts` the same way `resolved_apps` is set, and a test keeps each equal to its `group_vars/all` definition.
- `backup_agent`, `cloud_sync` and `restore_discovery` read `backup_plan`. None applies a backup default or tests whether an app is backed up itself.
- The hosts that back up are derived, not listed. A filter `backup_hosts(hosts, hostvars)` returns the hosts whose `backup_plan` is non-empty, in the order given. `backup_hosts` is defined once in `group_vars/all` as `"{{ groups['managed_hosts'] | backup_hosts(hostvars) }}"`. `seaweedfs_backup_hosts` is removed. The SeaweedFS identity template and `cloud_sync` read `backup_hosts`. Each host's own secret pair and `seaweedfs_s3_*` host variables stay hand-maintained; the catalog validator fails when a derived backup host lacks either.
- The catalog validator gains these rules. A `backup:` block must name at least one volume, so a block without volumes cannot exist to disagree with the filter. `backup` keys have the right shapes: `cloud_targets` a list of names, `retention_days` a positive integer, `compression` one of `gz`, `zst`, `none`, `stop_during_backup` a boolean, `cron` a non-empty string. The old key `extra_cloud_targets` is rejected, as `caddy` is. Each name in `cloud_targets`, and in the default, must be a key of `cloud_sync_targets`, read as plain YAML from `host_vars/storage.yaml` without rendering any value.
- Names that describe SeaweedFS say so. `offsite_backup_s3_bucket`, `offsite_backup_s3_endpoint` and `offsite_backup_s3_proto` become `seaweedfs_s3_bucket`, `seaweedfs_s3_endpoint` and `seaweedfs_s3_proto`, beside the existing `seaweedfs_s3_access_key`. `offsite_backup_freshness_buffer_hours` becomes `backup_freshness_buffer_hours`; it is not a per-app setting, so it stays outside `backup_defaults`. "Offsite" is kept only for the cloud copies.
- Role-internal variables keep their role prefix and are not renamed.

## Alternatives considered

- **Extend `resolve_apps` to fill in backup defaults.** The resolver's inputs are `(compose_apps, app_catalog)`, so this needs a third input or moving the default anyway, changes the contract [ADR 0065](../0065-where-app-defaults-and-host-intent-are-merged/revision-000.md) accepted, couples a generic merge to backup semantics, and queues every scenario that uses the resolver whenever backup logic changes.
- **Leave the three copies and add checks.** Cheapest, but the logic stays in three hand-written expressions, one of which already disagrees with the other two.
- **Hoist only a list of backed-up apps.** Settles the predicate but leaves each role applying defaults itself.
- **A separate backup catalog file.** Splits one app's definition across two files; the per-app `backup:` block is already in the catalog.
- **Keep `seaweedfs_backup_hosts` as an explicit list.** A reviewer sees each identity grant as a line in a diff. But the list repeats what `backup_plan` already says, and three places must agree by hand: the list, the secret pair and the host variables.
- **Build the host-to-plan mapping in Jinja and pass it to a filter.** Gives the same list, but spells out in the variable definition the loop the filter exists to hold.
- **Keep the `offsite_` names.** They read as if the SeaweedFS bucket were the off-site copy.

## Consequences

- One name for a setting at both levels, and one place that decides what is backed up. The plan can be printed to debug a deploy, and downstream roles can be tested against fixed plans.
- The renames touch the catalog, `group_vars/all`, `host_vars/storage.yaml`, four roles, the SeaweedFS identity template, Molecule scenarios and several topic docs. They ship as mechanical changes after the filter exists, each old name is removed when its last reader switches, and a test fails if one comes back.
- A host that gains a backed-up app is granted a SeaweedFS identity by that catalog change rather than by a separate list edit. The identity stays scoped to the host's own prefix ([ADR 0006](../0006-offsite-backup-credential-blast-radius/revision-000.md)) and needs the host's own credentials, which the validator requires.
- The first deploy after `seaweedfs_backup_hosts` is removed swaps two identity entries, which restarts SeaweedFS on `storage` once. It is applied outside the schedule in `backup_defaults.cron`.
- Docs that describe these settings change in the pull requests that change the behavior: `docs/topics/disaster-recovery/backup.md`, `docs/topics/disaster-recovery/cloud-sync.md`, `docs/topics/disaster-recovery/restore.md`, `docs/topics/deploy/deployment-flow.md`, `docs/topics/secrets/secrets-rotation.md`, `docs/topics/deploy/adding-an-app.md` and `docs/topics/engineering/molecule-testing.md`. Three comments that misstate where or how a default is defined are corrected with them.

## Invariants

- Only `backup_plan` applies a backup default or decides that an app is backed up.
- A backup setting has the same name in `backup_defaults` and in an app's `backup:` block.
- Cloud credentials stay only in `storage`'s host variables. `cloud_targets` holds names, never credentials.
- A host that receives a SeaweedFS identity is one whose plan is non-empty and that has its own secret pair.

## Non-goals

- Changing any catalog entry's value, or any default's value.
- Changing how `cloud_sync` copies, or how `restore_discovery` excludes, orders and detects collisions among apps. That logic is a separate candidate for a filter.
- Generating the per-host secret pairs.
- Changing the SeaweedFS bucket name or endpoint values.

## Validation

A pytest suite for `backup_plan` and the host derivation, including the case where a list value replaces the default. The validator's new rules with a failing example for each. A test that fails when a retired name (`extra_cloud_targets`, `offsite_backup_*`, `cloud_sync_default_targets`, `seaweedfs_backup_hosts`) appears outside the validator's rejection of the old catalog key. A test that keeps each Molecule stand-in equal to the `group_vars/all` definition. During the migration, an old-versus-new diff of the rendered job list, restore manifest and schedules against the real inventory.

## Reconsideration triggers

- A backup setting that must vary per host rather than per app.
- A consumer that needs state which is not a plain argument to the filter.
