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
4. **Decide keep vs. delete for on-disk content**, if the directory exists: `compose_cleanup_app_overrides[<stack>]` if the stack has a per-app override, otherwise the default `compose_cleanup_remove_content`. If the decision resolves to "remove," the stack directory (and everything bind-mounted under it) is deleted with `ansible.builtin.file: state=absent`; otherwise it's left in place and reported as preserved.

## Why "keep" is the default

Stacks in this repo use bind mounts, not named Docker volumes, so a stack's directory *is* its data — there's no separate volume acting as a safety net. `roles/compose/defaults/main.yaml` therefore defaults to stopping an orphaned stack but leaving its directory on disk, and only deletes content for apps that explicitly opt in:

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
- **`-e compose_cleanup_dry_run=true`** — a playbook-level flag read by both `cleanup.yaml` and `roles/compose/tasks/cleanup.yaml`. When set, the teardown/removal tasks are skipped and replaced with `debug` messages describing what *would* happen — including, for each stack, whether its content would be kept or deleted and why (`"irreversible - bind-mounted data included"` vs. `"stack stopped, data left in place"`).

## Usage

```sh
ansible-playbook cleanup.yaml --check --diff              # Ansible check mode
ansible-playbook cleanup.yaml -e compose_cleanup_dry_run=true   # explicit dry-run reporting
ansible-playbook cleanup.yaml --limit services             # scope to one host
```
