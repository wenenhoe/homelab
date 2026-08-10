# Cleanup: Removing Orphaned Compose Stacks

`ansible/playbooks/cleanup.yaml` is a standalone playbook (`hosts: app_hosts`) that tears down stacks a host still has deployed but no longer lists in its `compose_apps` — e.g. after removing an app's entry from `host_vars/<host>.yaml`. It's not part of `deploy.yaml` and has to be run explicitly.

## How an orphan is identified

For each host, "orphaned" means: present on disk under `compose_deploy_dir` **or** currently running as a Docker Compose project, but **not** in that host's resolved `compose_apps`.

1. `compose_cleanup_wanted_apps` — the host's current `compose_apps`, reduced to just their `.name`s.
2. `compose_cleanup_found_dirs` — every directory directly under `compose_deploy_dir` (`ansible.builtin.find`).
3. `compose_cleanup_compose_ls` — every running Compose project (`docker compose ls --format json`).
4. `compose_cleanup_orphaned_stacks` — the union of (2) and (3), minus (1), deduplicated and sorted.

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
compose_cleanup_dry_run: false
```

## Dry-running before you delete anything

Two independent ways to preview a cleanup run, and they can be combined:

- **`--check --diff`** — Ansible's own check mode. `ansible-playbook cleanup.yaml --check --diff`
- **`-e compose_cleanup_dry_run=true`** — a playbook-level flag read by both `cleanup.yaml` and `roles/compose/tasks/cleanup.yaml`. When set, the teardown/removal tasks are skipped and replaced with `debug` messages describing what *would* happen — including, for each stack, whether its directory and volumes would be kept or deleted.

## Usage

```sh
ansible-playbook cleanup.yaml --check --diff              # Ansible check mode
ansible-playbook cleanup.yaml -e compose_cleanup_dry_run=true   # explicit dry-run reporting
ansible-playbook cleanup.yaml --limit services             # scope to one host
```
