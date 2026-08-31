# Cleanup: Removing Orphaned Compose Stacks

`ansible/playbooks/cleanup.yaml` is a standalone playbook (`hosts: app_hosts`) that tears down stacks a host still has deployed but no longer lists in its `compose_apps` — e.g. after removing an app's entry from `host_vars/<host>.yaml` — and prunes volumes an app no longer declares. It's not part of `deploy.yaml` and has to be run explicitly. To delete a single file inside a volume that's staying in place (e.g. resetting a SQLite db), see [`volume-maintenance.md`](volume-maintenance.md) instead — that's a different, ad hoc operation this playbook doesn't cover.

## How an orphan is identified

For each host, "orphaned" means: present on disk under `compose_deploy_dir` **or** currently running as a Docker Compose project, but **not** in that host's resolved `compose_apps` **and not** in `compose_cleanup_exclude`.

1. `compose_cleanup_wanted_apps` — the host's current `compose_apps`, reduced to just their `.name`s.
2. `compose_cleanup_found_dirs` — every directory directly under `compose_deploy_dir` (`ansible.builtin.find`).
3. `compose_cleanup_compose_ls` — every running Compose project (`docker compose ls --format json`).
4. `compose_cleanup_orphaned_stacks` — the union of (2) and (3), minus (1) and `compose_cleanup_exclude`, deduplicated and sorted.

`compose_cleanup_exclude` (a `vars:` default on `cleanup.yaml`'s own Play 1, not a role default — see its own comment there) covers directories that are never going to be a `compose_apps` entry at all: `backup_agent` and `cloud_sync` are separate roles, included directly from `deploy.yaml`, not through the app registry, so without this they'd be misidentified as orphaned on every single run.

Union-ing disk and runtime state (not disk alone) catches a stack whose
containers are still running but whose directory was already deleted by
hand.

Each host reports "nothing to clean up" or the sorted orphan list, then
hands each name to `roles/compose/tasks/cleanup.yaml` to tear it down.

## Tearing down one stack

1. **Stat the stack directory** to pick a teardown path.
2. **Directory exists:** `community.docker.docker_compose_v2` brings it
   down (`state: absent, remove_orphans: true`), same module `deploy.yaml`
   uses to bring stacks up.
3. **Directory already gone:** list containers by their
   `com.docker.compose.project` label (`docker_host_info`), then
   force-remove them (`docker_container: state=absent, force_kill=true`).
4. **Decide keep vs. delete** for both on-disk content and named volumes,
   using `compose_cleanup_app_overrides[<stack>]` if set, else the default
   `compose_cleanup_remove_content`. "Remove" deletes the directory and
   every volume labelled `homelab.app=<stack>`; otherwise both are left
   and reported as preserved. Volumes are found by label, not the app's
   `app_registry` entry (gone once an app is orphaned) — see
   [`volumes.md`](volumes.md).

## Pruning stale volumes on stacks that are still deployed

The playbook's second play covers a different case: an app is still in
`compose_apps` (so Play 1 above never touches it), but its `app_registry`
entry no longer declares one of the volumes docker still has for it —
e.g. a `volumes` entry was removed or renamed while the app itself stays
deployed.

For each app, `roles/compose/tasks/cleanup_stale_volumes.yaml` compares
volumes found by the `homelab.app=<app>` label against the app's *current*
`.volumes | map(attribute='name')`, prefixed `<app>_` to match the naming
`ensure_volume.yaml` uses. Anything labelled but no longer declared is
stale. This needs `compose_apps` resolved against `app_registry`
(`preinit.yaml`), unlike Play 1, which only ever needed `.name`.

Governed by its own flag, independent of Play 1's
`compose_cleanup_remove_content`/`compose_cleanup_app_overrides` — a
stale volume on an active app is a different judgment call than tearing
down an entire orphaned stack:

```yaml
# roles/compose/defaults/main.yaml
compose_cleanup_stale_volume_remove: false   # default: report, don't delete
```

`compose_cleanup_dry_run` gates both plays the same way.

## Why "keep" is the default

Most apps' real data lives in named volumes (see
[`volumes.md`](volumes.md)), so deleting a stack's directory no longer
touches that data — but volume removal still uses the same explicit
decision as the directory (a few apps still use plain bind mounts, where
the directory *is* the data). Default: stop an orphaned stack, leave
directory and volumes in place, delete only apps that opt in:

```yaml
# roles/compose/defaults/main.yaml
compose_cleanup_remove_content: false      # default: stop, don't delete
compose_cleanup_app_overrides: {}          # per-app opt-in, e.g.:
#   old_test_app: true
#   scratch_service: true
compose_cleanup_dry_run: true              # default: report only, see below
```

## Dry-running before you delete anything

Two independent ways to preview a cleanup run, and they can be combined:

- **`--check --diff`** — Ansible's own check mode. `ansible-playbook cleanup.yaml --check --diff`
- **`compose_cleanup_dry_run`** — a playbook-level flag read by both `cleanup.yaml` and `roles/compose/tasks/cleanup.yaml`, **`true` by default**. While true, the teardown/removal tasks are skipped and replaced with `debug` messages describing what *would* happen — including, for each stack, whether its directory and volumes would be kept or deleted. A plain `ansible-playbook cleanup.yaml` with no extra flags is therefore already a dry run; pass **`-e compose_cleanup_dry_run=false`** to actually tear anything down.

## Usage

```sh
ansible-playbook cleanup.yaml                              # dry run (the default) — reports only
ansible-playbook cleanup.yaml --check --diff               # Ansible check mode, same effect
ansible-playbook cleanup.yaml -e compose_cleanup_dry_run=false  # actually tear down orphaned stacks
ansible-playbook cleanup.yaml -e compose_cleanup_dry_run=false --limit services  # scope to one host
```
