# Molecule Fixtures

A scenario's `files/docker/<app>/` is read directly off disk by
`compose_source_dir` (an Ansible controller-side path, not a Docker build
context), so a fixture can be a symlink and nothing downstream needs to
know — with one gotcha: `ansible.builtin.find`'s default `file_type`
never matches a symlink, even with `follow: true` (verified — that
option only affects recursion/stat-following, not this classification).
`compose/tasks/init.yaml`'s `find` for `compose*.yaml`/`Dockerfile*`
sets `file_type: any` because of this; any other `find`-based discovery
added later over a fixture directory needs the same.

## Apps with a real prod counterpart

`caddy`, `lldap`, `bind9`, and `tinyauth` symlink their compose file and
any `configs/*.j2` straight at `docker/<app>/` instead of keeping a
hand-copied duplicate. `bind9` symlinks `compose.yaml.j2` specifically
(see [`adding-an-app.md`](adding-an-app.md) for the `.j2` convention) —
it inlines `server_timezone` directly rather than carrying a separate
`.env`, so there's no `configs/env.j2` to symlink alongside it anymore.
This is stronger than keeping the two in sync by convention: Renovate
ignores symlinks outright, so a version-bump PR touches the one real
file, and the same test run that exercises the role exercises prod's
actual compose file — there's no separate fixture pin left to drift.

## `app_registry` entries

For scenarios that carry their own local copy (molecule never loads the
real inventory, so `host_vars/*.yaml` or `converge.yml`'s play `vars:`
duplicate the relevant entry rather than reference it — see `bind9`'s
`host_vars` for why it has to be a `host_vars` file specifically, not
play `vars:`), extract from the real registry instead of hand-copying
it:

```yaml
app_registry: >-
  {{
    (lookup('file', playbook_dir ~ '/../../../../inventory/group_vars/all/app_registry.yaml')
     | from_yaml).app_registry
    | combine({'testapp': {}})
  }}
```

`playbook_dir` here resolves to the *scenario's* directory (wherever
`converge.yml` lives), not wherever this expression is written.
`combine()` adds whatever synthetic fixture-only apps the scenario needs
(`testapp` above has no real registry entry to extract). Every scenario
with a real prod counterpart uses this now — `bind9`, `caddy`,
`caddy_cert_expiry`, `lldap_cert` (×2), `tinyauth`, and
`tinyauth_ca_trust`. `caddy_cert_expiry`'s `no_routed_apps` scenario is
the one holdout: its `app_registry` entries are empty stubs on purpose
(the guard it tests fires before that content would ever matter), not a
real duplicate at risk of drift. The remaining synthetic-app scenarios
(`compose`, `compose_app`, `backup_agent`, `restore`, ...) still
hand-copy an `app_registry` and always will — there's no real entry to
extract for a fixture app like `testapp`/`happy_app_a` that doesn't
exist in production.

## Cross-scenario generic fixtures

`configs/env.j2` (`GREETING=hello-from-{{ compose_app_item.name }}`),
`configs/seeded.txt.j2`, and `scripts/run.sh` were byte-identical across
scenarios purely because nothing in them ever referenced a specific app.
These live once under `ansible/roles/molecule_helpers/fixtures/`
(`generic_env.j2`, `generic_seeded.txt.j2`, `generic_run.sh`) and get
symlinked in. `molecule_helpers` is the right home for anything shared
across more than one role — `check_molecule_matrix`
(`.github/scripts/check-doc-drift.py`) excludes it from the scenario
matrix entirely, so nothing role-local has to carry it.

## Synthetic placeholder apps

The `alpine:3.20` / `sleep infinity` fixtures used to test
`compose`/`compose_app`'s batch logic mostly aren't identical to each
other — the volume count, `container_name`, `labels`, and `env_file`
presence *are* what each test is exercising, so keeping those as
distinct static files is clearer than templating one generic shape with
conditionals. Three shapes recur often enough to be worth a shared file
instead, all under `molecule_helpers/fixtures/`:

- `generic_alpine_app/compose.yaml` — no volume, no `container_name`,
  nothing else. No top-level `name:` either: Compose resolves the
  project name from, in order, a `-p` flag, `COMPOSE_PROJECT_NAME`, the
  file's own `name:`, then the containing directory's basename — the
  compose role's deploy calls pass none of the first two, so a fixture
  with no `name:` at all gets its project name from its directory,
  which is already the right value.
- `generic_alpine_app_with_volume/compose.yaml` — same, plus one volume
  mounted at `/data`. The external volume's `name:` uses
  `${COMPOSE_PROJECT_NAME}_data` interpolation instead of a literal
  string — confirmed live (`docker compose config`) that Compose
  exposes its own resolved project name for interpolation within the
  same file, matching what `ensure_volume.yaml` creates on the Ansible
  side. Upstream has an open issue about this being unreliable in some
  cases (`docker/compose#9530`) — if a future Compose version regresses
  it, this file is the first thing to check.
- `generic_alpine_app_with_env_file/compose.yaml` — no volume, plain
  `env_file: [.env]`. Not every app with `env_file` qualifies for this —
  only ones where the rendered `.env` content and its assertions live
  entirely in the *consuming* scenario (its own
  `app_registry`/`verify.yml`), not in the compose file itself.

## Container discovery without `container_name`

Fixtures that used to declare `container_name:` purely so
`verify.yml`/`converge.yml` could look them up by a fixed name
(`happy_app_nostop`, `restore_target`, etc.) now get discovered by
Compose project label instead, since a shared fixture can't carry a
distinct literal name — a `docker_host_info` lookup by
`com.docker.compose.project=<app>` label, feeding the discovered
container ID into `docker_container_info`. See
`ansible/roles/restore/molecule/default/verify.yml` for the pattern to
copy. Deliberately kept as two tasks rather than switching to
`docker_host_info`'s own `verbose_output` container shape — that keeps
the already-proven `.container.State.*` shape from `docker_container_info`
instead of trusting an unverified nested structure for something
version-drift could silently break.

## `molecule_helpers`'s shared task files

Scaffolding for scenarios, not a role under test:

| File | Used for |
| :--- | :--- |
| `playbooks/prepare_dind.yml` | Shared `prepare` playbook for scenarios on the bare base image (below). |
| `playbooks/prepare_dind_prebuilt.yml` | Shared `prepare` playbook for scenarios on the pre-baked DinD image (below) — coverage reset only. |
| `tasks/dind_storage_driver.yaml` | Forces the nested Docker daemon onto `fuse-overlayfs` via `/etc/docker/daemon.json`. |
| `tasks/install_docker_api_requests.yaml` | Installs `python3-requests`, needed by `community.docker` modules that talk to the Docker API directly. |
| `tasks/bootstrap_docker.yaml` | `include_role: docker` for scenarios that assume Docker is already installed, mirroring `deploy.yaml`'s Play 1. |
| `tasks/resolve_compose_apps.yaml` | Resolves a scenario's `compose_apps` against `app_registry`, same merge as `deploy.yaml`. |
| `tasks/start_seaweedfs_test_target.yaml` | Starts a real throwaway SeaweedFS S3 target with a real identity config (single-identity default, or a caller-supplied `molecule_helpers_seaweedfs_identity_json` for scenarios testing scoping across multiple identities — `identity_scoping` and `cloud_sync` both use this); exposes its IP as `molecule_helpers_seaweedfs_ip`. |
| `tasks/start_lldap_test_target.yaml` | Starts a real throwaway lldap target with a self-signed LDAPS cert, reachable under a caller-chosen network alias (needed for TLS hostname verification); exposes its IP as `molecule_helpers_lldap_ip`. |
| `tasks/reset_coverage_data.yaml` | Clears a scenario's `molecule-coverage` JSONL at `prepare` time (the callback appends, doesn't truncate). No-op if `MOLECULE_COVERAGE_DIR` isn't set. |
| `fixtures/` | Shared compose fixtures symlinked into multiple scenarios/roles — see the rest of this doc for what's in here and why. |
| `requirements.yml` / `role-requirements.yml` | Shared Galaxy collection/role deps (`community.docker`, `ansible.posix`). |

### Why `fuse-overlayfs`

The test container's own root filesystem is already overlay-mounted by
the host's Docker, and `overlay2` can't stack a second overlay on top of
that (`failed to mount ... fstype: overlay`). `fuse-overlayfs` is a
userspace overlay implementation that avoids that kernel-level stacking
restriction while still getting real copy-on-write, unlike `vfs`'s
full-copy-per-layer behavior — meaningfully faster for image pulls/builds
in the nested daemon. Test scaffolding only — real hosts keep using
`overlay2`.

### Shared `prepare`

`prepare_dind.yml` installs Docker, forces `fuse-overlayfs`, and
installs `python3-requests` — needed by any DinD scenario on the bare
`geerlingguy` base image instead of the pre-baked one below:

```yaml
# molecule.yml
provisioner:
  name: ansible
  playbooks:
    prepare: ${MOLECULE_PROJECT_DIRECTORY}/../molecule_helpers/playbooks/prepare_dind.yml
    converge: converge.yml
    verify: verify.yml
```

`docker`'s own scenario is the only one still on it today — see
"Pre-baked DinD image" below for why, and for what every other scenario
uses instead. `bind9` keeps its own `prepare.yml` regardless of which
image it's on (it manages its own `daemon.json` and would fight over the
same file, so it forces `fuse-overlayfs` via a systemd drop-in instead).
`apt` keeps a minimal `prepare.yml` whose only job is calling
`reset_coverage_data.yaml`.

### Pre-baked DinD image

`ghcr.io/wenenhoe/molecule-dind` (`docker/molecule-dind/Dockerfile`) is
the `geerlingguy/docker-ubuntu2604-ansible` base with Docker Engine,
`fuse-overlayfs`, and `python3-requests` already installed, so scenarios
on it skip all three `apt` installs `prepare_dind.yml` otherwise does on
every run. They use `prepare_dind_prebuilt.yml` (coverage reset only)
and drop the `bootstrap_docker.yaml` include from `converge.yml`, relying
on the daemon systemd starts at container boot.

`docker`'s own scenario is never migrated to this image — it tests that
installation from a clean base, and baking Docker in would make that
test tautological. `bind9` uses it too: its own storage-driver override
doesn't touch the baked `daemon.json`, so only its now-redundant
`fuse-overlayfs` package install and `python3-requests` install were
dropped from its own `prepare.yml`, the systemd drop-in stays.

Every other DinD scenario is on this image. Migrating one: swap the
`image:` and `prepare:` playbook in `molecule.yml`, then delete the
`bootstrap_docker.yaml` include task (and the `install_docker_api_requests.yaml`
one right after it, where present) from `converge.yml`.

### Base config

`.config/molecule/config.yml` at the repo root is Molecule's auto-discovered
base config, deep-merged into every scenario before that scenario's own
`molecule.yml` applies. It supplies the shared `dependency` collections
and `provisioner.env` to every scenario — nothing to add for a new one
beyond its own `molecule.yml`.
