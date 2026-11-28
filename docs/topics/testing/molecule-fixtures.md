# Molecule Fixtures

A scenario's `files/docker/<app>/` is read off disk on the controller by
`compose_source_dir`, so a fixture can be a symlink, with one catch: `ansible.builtin.find`'s default `file_type`
never matches a symlink, even with `follow: true` (verified — that
option only affects recursion/stat-following, not this classification).
`compose/tasks/init.yaml`'s `find` for `compose*.yaml`/`Dockerfile*`
sets `file_type: any` because of this; any other `find`-based discovery
added later over a fixture directory needs the same.

## Apps with a real prod counterpart

`caddy`, `lldap`, `openbao`, `bind9`, `tinyauth` and `bentopdf` symlink their compose file and any
`configs/*.j2` to `docker/<app>/` rather than keeping a copy (`bind9` links `compose.yaml.j2`, which
inlines `server_timezone`; see [`adding-an-app.md`](../deploy/adding-an-app.md)). Renovate ignores
symlinks, so a version bump touches only the real file and the role's tests run against what
production runs.

## `app_catalog` entries

For scenarios that carry their own local copy (molecule never loads the
real inventory, so `host_vars/*.yaml` or `converge.yml`'s play `vars:`
duplicate the relevant entry rather than reference it — see `bind9`'s
`host_vars` for why it has to be a `host_vars` file specifically, not
play `vars:`), extract from the real catalog instead of hand-copying
it:

```yaml
app_catalog: >-
  {{
    (lookup('file', playbook_dir ~ '/../../../../inventory/group_vars/all/app_catalog.yaml')
     | from_yaml).app_catalog
    | combine({'testapp': {}})
  }}
```

`playbook_dir` resolves to the *scenario's* directory. `combine()` adds the fixture-only apps
(`testapp` has no real entry). A scenario with a real production counterpart extracts it this way.
The exceptions keep their own entries: `caddy_cert_expiry`'s `no_routed_apps`, whose empty stubs are
never read past the guard it tests, and scenarios for apps that don't exist in production.

## Cross-scenario generic fixtures

Fixtures that reference no particular app live once under `ansible/roles/molecule_helpers/fixtures/`
(`generic_env.j2`, `generic_seeded.txt.j2`, `generic_run.sh`) and are symlinked in. Anything shared by
more than one role goes in `molecule_helpers`, which the scenario matrix check
(`check_molecule_matrix` in `tools/doc_scripts/check_doc_drift.py`) leaves out.

## Synthetic placeholder apps

The `sleep infinity` fixtures for `compose`/`compose_app` mostly differ on purpose (volume count,
`container_name`, `labels`, `env_file` are what each tests), so they stay separate files. Three
recurring shapes are shared under `molecule_helpers/fixtures/`:

| Fixture | Shape | Note |
| :--- | :--- | :--- |
| `generic_alpine_app/compose.yaml` | No volume, no `container_name`, no top-level `name:` | The compose role passes no `-p` or `COMPOSE_PROJECT_NAME`, so the directory name becomes the project name, which is the right value. |
| `generic_alpine_app_with_volume/compose.yaml` | Plus one volume at `/data` | Its external `name:` is `${COMPOSE_PROJECT_NAME}_data`, matching `ensure_volume.yaml`. `docker/compose#9530` reports this interpolation as unreliable in some cases; check this file first if a Compose bump breaks it. |
| `generic_alpine_app_with_env_file/compose.yaml` | No volume, `env_file: [.env]` | Only for apps whose rendered `.env` and its assertions live wholly in the consuming scenario. |

## Container discovery without `container_name`

A shared fixture can't carry a distinct `container_name`, so `converge.yml`/`verify.yml` find
containers by project label: `docker_host_info` filtered on `com.docker.compose.project=<app>`, then
`docker_container_info` on the ID. Keep both tasks: the `.container.State.*` shape is the proven one,
unlike `docker_host_info`'s `verbose_output` structure. Pattern to copy:
`ansible/roles/restore/molecule/default/verify.yml`.

## Fixtures for hardened containers

A scenario that tests a container with dropped capabilities
([`container-hardening.md`](../deploy/container-hardening.md)) only proves
something if its fixture can fail the way production does:

- **Derive the fixture from production config.** Run the same `cap_drop`,
  `cap_add`, `read_only`, `user` and `tmpfs` the app or role sets, taken from
  the real file rather than retyped.
- **Give the fixture the owners production has.** Files owned by root prove
  nothing about `CHOWN`, `FOWNER` or `DAC_OVERRIDE`, because root needs none
  of them for its own files. Stage files owned by another uid and gid, with a
  non-default mode, and a `2775` directory where the setgid bit matters.
- **Assert owner, group and mode, as well as the exit code.** `cp -a` and
  `tar` can exit 0 and leave the wrong metadata.
- **Run the unit's own command.** For a systemd service, read the `docker
  run` line back with `systemctl cat` and run it, rather than a copy typed
  into the test.
- **Test an empty volume and a populated one.** Docker resets an empty named
  volume's top directory to the image's owner on mount, so set the owner after
  putting a file in it.
- **Restart once.** A scenario that boots a hardened service also restarts it
  and asserts it is healthy with no restarts counted.

## `molecule_helpers`'s shared task files

Scaffolding for scenarios, not a role under test:

| File | Used for |
| :--- | :--- |
| `playbooks/prepare_dind.yml` | Shared `prepare` playbook for scenarios on the bare base image (below). |
| `playbooks/prepare_dind_prebuilt.yml` | Shared `prepare` playbook for scenarios on the pre-baked DinD image (below) — coverage reset only. |
| `tasks/dind_storage_driver.yaml` | Forces the nested Docker daemon onto `fuse-overlayfs` via `/etc/docker/daemon.json`. |
| `tasks/install_docker_api_requests.yaml` | Installs `python3-requests`, needed by `community.docker` modules that talk to the Docker API directly. |
| `tasks/resolve_compose_apps.yaml` | Sets `resolved_apps` from a scenario's `compose_apps` and `app_catalog` with the `resolve_apps` filter, as `group_vars/all` does for production, and creates the stacks directory. |
| `tasks/resolve_backup_plan.yaml` | Sets `backup_plan` from a scenario's `resolved_apps` and `backup_defaults` with the `backup_plan` filter, as `group_vars/all` does for production. Runs after `resolve_compose_apps.yaml`, for a role that reads its own host's plan. |
| `tasks/start_seaweedfs_test_target.yaml` | Starts a real throwaway SeaweedFS S3 target with a real identity config (single-identity default, or a caller-supplied `molecule_helpers_seaweedfs_identity_json` for scenarios testing scoping across multiple identities — `identity_scoping` and `cloud_sync` both use this); exposes its IP as `molecule_helpers_seaweedfs_ip`. |
| `tasks/start_lldap_test_target.yaml` | Starts a real throwaway lldap target with a self-signed LDAPS cert, reachable under a caller-chosen network alias (needed for TLS hostname verification); exposes its IP as `molecule_helpers_lldap_ip`. |
| `tasks/reset_coverage_data.yaml` | Clears a scenario's `molecule-coverage` JSONL at `prepare` time (the callback appends, doesn't truncate). No-op if `MOLECULE_COVERAGE_DIR` isn't set. |
| `vars/helper_names.yml` | Container names and host directories for the step-ca and OpenBao helpers, derived from the role and scenario so scenarios can run side by side. A scenario loads it in its converge, verify and cleanup playbooks; the helpers read the variables it defines, and keep their old fixed names where a scenario does not load it. |
| `vars/images/<name>.yml` | One file per image the Molecule playbooks run directly (`alpine`, `aws_cli`, `curl`, `lldap`, `step_cli`), each defining `molecule_helpers_<name>_image`. See [Shared image pins](#shared-image-pins). |
| `fixtures/` | Shared compose fixtures symlinked into multiple scenarios/roles — see the rest of this doc for what's in here and why. |
| `requirements.yml` / `role-requirements.yml` | Shared Galaxy collection/role deps (`community.docker`, `ansible.posix`). |

### Shared image pins

A converge, verify or cleanup playbook never writes an image literal. It
loads the file for each image it uses and references the variable:

```yaml
vars_files:
  - "{{ playbook_dir }}/../../../molecule_helpers/vars/images/alpine.yml"
```

then `image: "{{ molecule_helpers_alpine_image }}"`, or the same
expression inside a `docker run` string. Each file holds one line,
`molecule_helpers_<name>_image: "<repo>:<tag>"`, quoted: Renovate's regex
manager reads that shape. A task file a play imports uses the variables
its importing play loaded.

There is one file per image, and a play loads only the ones it uses,
because CI queues a role by the files its scenarios reference
([`molecule_scope.py`](../../../tools/ci/scope/molecule_scope.py)). A bump to
`curl.yml` reruns the roles that load it, not every role that uses any
test image. The files are loaded per play rather than through the base
config below for the same reason: CI reruns every scenario when the base
config changes.

Renovate's ansible manager only reads `tasks/`, so a regex manager in
`.github/renovate.json5` tracks these files, and a `packageRules` group
per image keeps its copies in prod tasks and compose fixtures in the same
PR. Fixture `compose.yaml` files can't use Ansible variables and keep
their own pin, which the `docker-compose` manager tracks.

The `check-molecule-image-vars` pre-commit hook
([`molecule_vars.py`](../../../tools/ci/images/molecule_vars.py)) enforces all
of this on every PR: no image literal in a scenario's playbooks, every
play loading exactly the files it uses, and every image file loaded by
some play.

### Why `fuse-overlayfs`

The test container's root filesystem is already an overlay, and `overlay2` can't stack on it
(`failed to mount ... fstype: overlay`). `fuse-overlayfs` is userspace, so it can, and unlike `vfs` it
copies on write. Test scaffolding only: real hosts use `overlay2`.

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

Only `docker`'s scenario uses it. `bind9` keeps its own `prepare.yml` (it manages `daemon.json`, so
forces `fuse-overlayfs` through a systemd drop-in), and `apt` keeps a minimal one that only calls
`reset_coverage_data.yaml`.

### Pre-baked DinD image

`ghcr.io/wenenhoe/molecule-dind` (`docker/molecule-dind/Dockerfile`) is
the `geerlingguy/docker-ubuntu2604-ansible` base with Docker Engine,
`fuse-overlayfs`, and `python3-requests` already installed, so scenarios
on it skip all three `apt` installs `prepare_dind.yml` otherwise does on
every run. They use `prepare_dind_prebuilt.yml` (coverage reset only)
and `converge.yml` installs nothing Docker-related, relying on the daemon
systemd starts at container boot.

Every scenario on this image names it as `:latest@sha256:…`, the digest of a build
whose workflow attested it. A regex manager in `.github/renovate.json5` moves
the digest in all the scenarios together after each weekly rebuild, and the
[provenance check](../engineering/ci/image-provenance-check.md) verifies it.

`docker`'s scenario never uses it: it tests that installation from a clean base. `bind9` does, keeping
its systemd drop-in. Every other DinD scenario is on it. To move one, change `image:` and the `prepare:`
playbook in `molecule.yml`, then delete the Docker install tasks from `converge.yml` (including
`install_docker_api_requests.yaml`).

### Base config

`.config/molecule/config.yml` at the repo root is Molecule's auto-discovered
base config, deep-merged into every scenario before that scenario's own
`molecule.yml` applies. It supplies the shared `dependency` collections
and `provisioner.env` to every scenario — nothing to add for a new one
beyond its own `molecule.yml`.
