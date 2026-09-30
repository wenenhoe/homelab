---
id: PROJ-backup-plan
title: "Backup Plan"
type: project
status: building
blocked: false
summary: "One backup_defaults block and one backup_plan filter replace three roles' hand-written backup defaults and the hand-maintained backup host list, with matching renames and validator rules."
decision: ADR-0068/0
---

# Backup Plan

Replaces the backup defaults that `backup_agent`, `cloud_sync` and `restore_discovery` each apply in their own Jinja with one `backup_plan` filter and one `backup_defaults` block, derives the list of backup hosts from the plan, and renames the shared variables so a default and the setting it defaults share a name. Staged so the filter is proven, and each consumer's output shown unchanged against the real inventory, before the next consumer switches.

## Scope

The new filter and its tests; `backup_defaults` in `group_vars/all`; the `backup_agent`, `cloud_sync`, `restore_discovery` and `seaweedfs_bucket` roles; the SeaweedFS identity template; the catalog key rename and the catalog validator; Molecule scenarios that name a retired variable; the topic docs the ADR lists.

Not in scope: changing any catalog entry's or default's value, `cloud_sync`'s copy behavior, `restore_discovery`'s exclusion, ordering and collision logic, generating the per-host secret pairs, and the resolver from [ADR 0065](../decisions/0065-where-app-defaults-and-host-intent-are-merged/revision-000.md).

## Decision

Implements [ADR 0068](../decisions/0068-where-per-app-backup-settings-get-their-defaults/revision-000.md), `approved`. Stage 1, a throwaway spike, resolved the revision's two assumptions before approval.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | De-risk: run a throwaway `backup_plan` and host derivation over the real inventory through Ansible | Done | Both ADR assumptions are resolved and their entries deleted: the filter accepts a lazily templated `resolved_apps`, the derived host list is `services`, `play`, `security` from `storage`'s play and from the controller, and the identity template renders the same entries in a different order. All held; the entries are deleted and the facts are in the ADR's Context |
| 2 | `backup_plan` and `backup_hosts` filters, the `backup_defaults` block and the `backup_hosts` variable, with unit tests; no consumer changes | Not started | Unit tests cover default application, list replacement, an app with no `backup:` block, an app with empty `backup.volumes`, and the derived hosts, including a host whose plan is empty and the order given; a test keeps each `backup_defaults` value equal to the variable it will replace until that variable is removed |
| 3 | Rename `extra_cloud_targets` to `cloud_targets`; switch `cloud_sync` and `restore_discovery` to `backup_plan`; remove `cloud_sync_default_targets` | Not started | The old-versus-new diff of `cloud_sync_jobs` and the restore manifest is empty against the real inventory; the validator rejects the old key; the `cloud_sync` and `restore_discovery` Molecule scenarios pass in CI |
| 4 | Switch `backup_agent` to `backup_plan`; remove `offsite_backup_cron` and `offsite_backup_retention_days` | Not started | The old-versus-new diff of the rendered schedules is empty against the real inventory; the `backup_agent` Molecule scenarios pass in CI |
| 5 | Switch to the derived backup hosts; remove `seaweedfs_backup_hosts` | Not started | The SeaweedFS identity template and `cloud_sync` read `backup_hosts`; the identity file differs from before only in entry order; the `cloud_sync` and `seaweedfs_bucket` scenarios, which set the old list for fake hosts, set `backup_hosts` instead and pass in CI |
| 6 | Rename `offsite_backup_s3_*` to `seaweedfs_s3_*` and `offsite_backup_freshness_buffer_hours` to `backup_freshness_buffer_hours` | Not started | Every reference is updated, each hit checked; rendered output is unchanged; every Molecule scenario that named an old variable passes in CI |
| 7 | Validator rules, retired-name guard test, topic docs and the three stale comments | Not started | The validator fails on a `backup:` block with no volumes, a malformed backup key, and an unknown cloud target, each with a failing example; the guard test fails when a retired name returns; the docs the ADR lists describe the new behavior |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] No role, template or playbook applies a backup default or tests whether an app is backed up other than by reading `backup_plan`.
- [ ] `extra_cloud_targets`, `offsite_backup_*`, `cloud_sync_default_targets` and `seaweedfs_backup_hosts` appear nowhere except the validator's rejection of the old catalog key.
- [ ] The rendered job list, restore manifest and schedules are unchanged against the real inventory, and the identity file differs only in entry order.
- [ ] The validator rejects each of the cases named in stage 7.
- [ ] Every Molecule scenario that used a retired name passes in CI.

## Agent handoff

- **Allowed to change:** no `allowed_paths` yet (see Open items); the files under Relevant files and interfaces, and the docs the ADR lists.
- **Must not change:** any catalog entry's or default's value; where `cloud_sync_targets` lives; the resolver's contract; how `cloud_sync` copies or how `restore_discovery` excludes, orders and detects collisions.
- **Relevant files and interfaces:** `ansible/filter_plugins/` (`resolve_apps.py`, `cron_period_hours.py` are the precedents), `ansible/inventory/group_vars/all/`, `ansible/inventory/host_vars/storage.yaml`, `ansible/roles/backup_agent/tasks/build_schedules.yaml`, `ansible/roles/cloud_sync/tasks/main.yaml`, `ansible/roles/restore_discovery/tasks/main.yaml`, `docker/seaweedfs/configs/s3-identity.json.j2`, `ansible/roles/molecule_helpers/`, `tools/ci/gates/app_catalog_rules.py`.
- **Required checks:** the filter's pytest suite; the old-versus-new diff of each consumer's rendered output against the real inventory, run from a tiny playbook that extracts the role's real task from each tree; the `pre-commit` hooks that run without Docker; `python -m ci.scope.molecule_scope <base> <head>` to see which scenarios a change queues; a negative control for every new guard.

## Risks

- No Docker in the authoring sandbox, so Molecule scenarios run only in CI; a scenario that depended on a tolerance the old code had would surface there. List what each replaced expression silently tolerated before removing it.
- The reordered identity file restarts SeaweedFS on `storage` once, at the first deploy after stage 5. Deploy it outside the schedule in `backup_defaults.cron`.
- Two Molecule scenarios (`cloud_sync` default and `seaweedfs_bucket` identity_scoping) name fake backup hosts through `seaweedfs_backup_hosts` and `add_host`, which a list derived from `managed_hosts` does not cover; each needs a `backup_hosts` stand-in like the `resolved_apps` one.
- Each rename shares tokens with unrelated names (`backup_agent`, `backup_dir`, `seaweedfs_bucket`, the role of that name); exact-token search and a check of every hit, not a pattern replace.

## Open items

- Set `allowed_paths` once stage 2 settles the file set; widening it later is its own change.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or named by a successor project.
- [ ] The linked revision is `accepted`, another project still names it, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
