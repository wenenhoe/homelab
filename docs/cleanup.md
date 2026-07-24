# Cleanup: Removing Orphaned Compose Stacks

`ansible/cleanup.yaml` is a standalone playbook (`hosts: app_hosts`) that tears down stacks a host still has deployed but no longer lists in its `compose_apps` — e.g. after removing an app's entry from `host_vars/<host>.yaml`. It's not part of `deploy.yaml` and has to be run explicitly.

## How an orphan is identified

For each host, "orphaned" means: present on disk under `compose_deploy_dir` **or** currently running as a Docker Compose project, but **not** in that host's resolved `compose_apps`.

1. `compose_cleanup_wanted_apps` — the host's current `compose_apps`, reduced to just their `.name`s.
2. `compose_cleanup_found_dirs` — every directory directly under `compose_deploy_dir` (`ansible.builtin.find`).
3. `compose_cleanup_compose_ls` — every running Compose project (`docker compose ls --format json`).
4. `compose_cleanup_orphaned_stacks` — the union of (2) and (3), minus (1), deduplicated and sorted.

Union-ing disk and runtime state (rather than relying on disk alone) is what catches the edge case handled below: a stack whose containers are still running but whose directory has already been deleted by hand.

Each host reports either "nothing to clean up" or the sorted list of orphaned stack names, then the playbook loops over that list and hands each stack name off to the `compose` role's `cleanup.yaml` tasks (`roles/compose/tasks/cleanup.yaml`) to actually tear it down.

## Tearing down one stack

For a given orphaned stack name, `roles/compose/tasks/cleanup.yaml` runs:

1. **Stat the stack directory.** Whether it still exists on disk decides which teardown path runs next.
2. **Normal case — directory exists:** `community.docker.docker_compose_v2` brings it down with `state: absent, remove_orphans: true`, resolving services/networks from the compose files on disk (same module the `compose` role's `deploy.yaml` uses to bring stacks up).
3. **Fallback case — directory is already gone** (e.g. removed by hand outside Ansible, so there's nothing for `docker_compose_v2` to read): list containers by their `com.docker.compose.project` label via `docker ps -aq`, then force-remove whatever's found with `docker rm -f`.
4. **Decide keep vs. delete for on-disk content and named volumes**, using the same decision for both: `compose_cleanup_app_overrides[<stack>]` if the stack has a per-app override, otherwise the default `compose_cleanup_remove_content`. If the decision resolves to "remove," the stack directory is deleted with `ansible.builtin.file: state=absent`, and every Docker volume labelled `homelab.app=<stack>` is removed with `community.docker.docker_volume: state=absent`; otherwise both are left in place and reported as preserved. Volumes are discovered by label rather than the app's old `app_registry` entry, since that entry — and its declared `volumes` list — no longer exists once an app is orphaned. See [`volumes.md`](volumes.md) for how that label gets applied in the first place.

## Why "keep" is the default

Most apps' real data now lives in named Docker volumes (see [`volumes.md`](volumes.md)), not bind mounts, so deleting a stack's directory no longer touches that data on its own — the directory mainly holds compose files and rendered configs. Volume removal is still gated behind the exact same decision as the directory, though, so it stays a deliberate, explicit choice rather than a side effect of tidying up a directory (and a few apps still use plain bind mounts, where the directory *is* the data). `roles/compose/defaults/main.yaml` therefore defaults to stopping an orphaned stack but leaving its directory and volumes in place, and only deletes content for apps that explicitly opt in:

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
