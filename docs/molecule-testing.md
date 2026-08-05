# Molecule Testing

Each role is tested in isolation with [Molecule](https://ansible.readthedocs.io/projects/molecule/), using the co-located convention: a role's scenarios live under `ansible/roles/<role>/molecule/<scenario>/`. Molecule brings up a real Docker container per scenario, converges the role into it, verifies the result, then re-converges to check idempotence, mirroring what `deploy.yaml` does against real hosts.

## Scenario matrix

| Role | Scenario(s) | What it covers |
| :--- | :--- | :--- |
| `apt` | `default` | Package updates only — no systemd, no privileged mode, no Docker-in-Docker needed at all. |
| `fwupd` | *(none)* | Talks to real firmware/LVFS hardware, which a container can't meaningfully simulate. |
| `docker` | `default` | Installing Docker Engine itself, inside a privileged/systemd container with `/sys/fs/cgroup` exposed. |
| `compose` | `default` | The main init/deploy happy path. |
| | `volumes` | Named-volume creation, legacy bind-mount migration, config seeding, and full teardown — everything `default` deliberately skips. |
| | `scripts` | The two script-deployment paths in `init.yaml`: direct copy vs. volume-seeded. |
| | `build` | The `build: true` branch of `deploy.yaml`, currently unused by any real app but still covered. |
| | `cleanup` | `cleanup.yaml`'s dry-run mode, the keep-content path, `compose_cleanup_app_overrides`, and the label-fallback teardown when a stack's directory is already gone. |
| `compose_app` | `default` | Batch-driving `compose/` across multiple apps, continuing past a failed one. |
| | `strict` | `compose_app_continue_on_error: false` — the opposite of `default`. |
| | `continue_on_error` | One deliberately-broken app (missing config source) alongside two healthy ones and `bind9`/`caddy`: the batch reports the expected failure (rescue-block marker), the healthy apps deploy anyway, the broken one never gets a container, and the self-managed apps (`bind9`/`caddy`, excluded from `compose_app`'s own batch by design) are never touched at all. |
| `caddy` | `default` | The custom DigitalOcean-DNS Caddy build (xcaddy from source) and deploy via `compose`. Slowest scenario — compiling Caddy typically takes a couple of minutes and needs real internet access for Go modules. |
| | `unregistered` | `caddy_has_compose_app == false` — the role runs but `compose_apps` has no `caddy` entry at all (true of every real host today, but explicitly supported code). Config still renders and the custom image still builds — neither depends on caddy being a compose app — but nothing gets seeded into a volume and no container gets deployed. Added after tracing this branch surfaced a real bug (a seed task gated on the wrong condition, fixed alongside this scenario). |
| `bind9` | `default` | Zone-file aggregation/rendering/reload against a single instance that's a member of `app_hosts` itself (so it ends up serving DNS data about itself) — not a perfect topology match to the real multi-host setup, but exercises the real scraping/templating logic. |
| `backup_agent` | `default` | The main aggregation happy path: apps split correctly into the stop-during-backup vs. no-stop groups, a real (throwaway) SeaweedFS target standing in for S3, and a manually-triggered backup for each group asserted against real evidence — the stopped group's container `StartedAt` actually changes, the no-stop group's never does, and the archive actually lands in the test bucket. |
| | `conflict` | Two apps sharing a group but disagreeing on `retention_days`/`cron` — validation must fail loudly before rendering `compose.yaml` or touching any volume, asserted via a rescue-block marker plus confirming nothing was created. |
| | `no_stop_group_only` | The no-stop group populated, stop-during-backup group empty — a branch `default` (which always populates both) and `conflict` (stop-group only) never exercise. |
| | `stop_group_only` | The mirror image of `no_stop_group_only`: stop-during-backup populated, no-stop empty. |
| `restore` | `default` | The full happy-path restore of a single volume: real stop → extract → overwrite → redeploy against a real archive, with a StartedAt check and a content check proving the volume was actually rewritten, not just that the tasks reported success. |
| | `multi_volume` | Multiple volumes restored out of one archive at different nesting depths, alongside a decoy directory (prefix-similar name) and an unrelated app's directory that must both be ignored — the "find the directory matching this name wherever it sits, ignore everything else" logic `roles/restore/tasks/main.yaml` documents. |
| | `validation_failure` | The vars/archive-existence gate: an archive path that doesn't exist must block every destructive step. Asserts the actual side effects (StartedAt unchanged, volume content unchanged, no scratch volume, no archive copy on the target), not just that the task failed. |
| | `confirmation_declined` | The other, independent gate: valid vars/archive, but confirmation explicitly declined (`restore_confirm: false`) rather than relying on Molecule's own ansible-playbook subprocess lacking a tty — it doesn't reliably, see the confirmation-gate comment in `roles/restore/tasks/main.yaml`. Same side-effect assertions as `validation_failure`. |

`restore`'s `default`/`multi_volume` scenarios deliberately don't run an `idempotence` step — see the comment in their `molecule.yml` (a restore is meant to unconditionally re-execute on every invocation, not converge to a no-op). `confirmation_declined` doesn't either, for an unrelated reason: it needs a real archive to exist (the archive-existence check runs before the confirmation gate), and the fixture task that builds it deliberately deletes and rebuilds unconditionally every run, so it always reports changed regardless of the role's own behavior. `validation_failure` keeps `idempotence` — it never creates a file at all, so it stays genuinely idempotent.

Run a single scenario:

```sh
cd ansible/roles/apt
molecule test
```

Run a non-default scenario with `-s`:

```sh
cd ansible/roles/compose
molecule test -s volumes
```

Run every scenario of every role in one go, from `ansible/`:

```sh
./molecule-test-all.sh          # every role
./molecule-test-all.sh compose  # just one
```

This exists because `molecule test --all` doesn't work directly from
`ansible/` - Molecule's scenario-discovery glob is relative to cwd and
doesn't recurse into `roles/*/molecule/*/molecule.yml` on its own, and
pointing `MOLECULE_GLOB` at a recursive pattern to fix that surfaces a
second problem: Molecule validates scenario names for uniqueness across
everything the glob discovers, not per-role, and 8 of this repo's 21
scenarios are named `default`. `molecule-test-all.sh` sidesteps both by
running `molecule test --all` once per role directory, so each invocation
only ever sees that one role's own (already-unique) scenario names.

## `molecule_helpers`

`ansible/roles/molecule_helpers/` isn't a role under test — it's a shared library of scaffolding for the other scenarios, so common setup doesn't get copy-pasted across every one of them:

| File | Used for |
| :--- | :--- |
| `playbooks/prepare_dind.yml` | The shared `prepare` playbook (see below). |
| `tasks/dind_vfs_storage_driver.yaml` | Forces the nested Docker daemon onto the `vfs` storage driver via `/etc/docker/daemon.json`. |
| `tasks/install_docker_api_requests.yaml` | Installs `python3-requests`, needed by `docker_volume`/`docker_host_info` and other `community.docker` modules that talk to the Docker API directly rather than through the CLI plugin. |
| `tasks/bootstrap_docker.yaml` | `include_role: docker` — for scenarios whose role-under-test assumes Docker is already installed (`compose`, `compose_app`, `caddy`, `bind9`, `backup_agent`, `restore`), mirroring Play 1 of the real `deploy.yaml`. |
| `tasks/resolve_compose_apps.yaml` | Resolves a scenario's `compose_apps` against its `app_registry`, the same merge `deploy.yaml` does per-host. |
| `requirements.yml` / `role-requirements.yml` | Shared Galaxy collection/role dependencies (`community.docker`, `ansible.posix`), referenced from each scenario's `molecule.yml` instead of every scenario keeping its own copy. |

### Why the nested Docker daemon needs `vfs`

The test container's own root filesystem is already overlay-mounted by the *host's* Docker, and the `overlay2` driver can't stack a second overlay filesystem on top of that (`failed to mount ... fstype: overlay ... err: invalid argument`). `vfs` is slower and skips copy-on-write, but it's the reliable fallback for Docker-in-Docker and is fine for the small test images used here. This is test-scaffolding only — real target hosts (bare metal/VMs) don't have this problem and should keep using `overlay2`.

### The shared `prepare` playbook

Every Docker-in-Docker scenario except `bind9` needs the exact same two things before `converge`: the `vfs` storage-driver override above, and `python3-requests`. Rather than each scenario keeping an identical `prepare.yml`, they all point at one shared playbook:

```yaml
# molecule.yml
provisioner:
  name: ansible
  playbooks:
    prepare: ${MOLECULE_PROJECT_DIRECTORY}/../molecule_helpers/playbooks/prepare_dind.yml
    converge: converge.yml
    verify: verify.yml
```

`bind9` is the one exception, and keeps its own `prepare.yml`: it manages its own `daemon.json` for DNS settings and would fight over the same file if the shared playbook also wrote `storage-driver` into it, so it forces `vfs` via a systemd drop-in override instead. `apt` needs neither and has no `prepare.yml` at all.

### The base config

`ansible/roles/apt/molecule/default/molecule.yml`'s `provisioner` section (and every other scenario's) doesn't declare an `env:` block, and none of the 21 scenarios declare `dependency:` either — even `apt`, which doesn't actually need the shared `role-requirements.yml`/`requirements.yml` collections, inherits them anyway (a deliberate tradeoff: a marginal, already-cached lookup cost, in exchange for zero per-scenario duplication instead of 20/21). Both live in `.config/molecule/config.yml` at the repo root instead — Molecule's "base config", auto-discovered there without any `-c`/`--base-config` flag, and deep-merged into every scenario's own `molecule.yml` before that scenario's config is applied on top. A new scenario inherits these automatically; nothing to add for them beyond the scenario's own `molecule.yml`.

## Adding a new scenario

1. Copy an existing scenario directory (pick the closest match — e.g. `compose/molecule/default` for anything that deploys via Compose) rather than starting from scratch.
2. If the role-under-test assumes Docker is already running, point `converge.yml` at `molecule_helpers` for `bootstrap_docker.yaml` (and `resolve_compose_apps.yaml` if it uses `app_registry`/`compose_apps`) instead of duplicating that logic.
3. If the scenario needs Docker-in-Docker (privileged container, `cgroupns_mode: host`, `/sys/fs/cgroup` mounted), point `prepare` at `molecule_helpers/playbooks/prepare_dind.yml` rather than writing a new `prepare.yml` — unless, like `bind9`, the role's own tasks conflict with the shared one's `daemon.json` write.
4. Don't add `dependency.options` — `.config/molecule/config.yml` (Molecule's base config) already points every scenario at the shared `role-requirements.yml`/`requirements.yml`, `apt` included.
5. Don't add a `provisioner.env` block for `ANSIBLE_ROLES_PATH`/`ANSIBLE_CONFIG`/the `molecule-coverage` callback vars — `.config/molecule/config.yml` at the repo root (Molecule's base config) already supplies those to every scenario automatically.
6. Run `molecule test` locally before opening a PR — there's no CI wired up for this yet, so it's the only check that catches a broken scenario (including idempotence, not just `verify.yml`).

## What molecule scenarios can't catch: tag wiring

Every `converge.yml` above calls its role directly (`include_role: name: bind9`), never through `deploy.yaml`. That's the right choice for testing a role's actual logic in isolation, but it means the `images`/`infra` tag scheme (see [`deployment-flow.md`](deployment-flow.md#tags)) is structurally invisible to these scenarios — `deploy.yaml`'s own `Include <role>` wrapper tasks are what a run like `--tags images` actually depends on to reach anything inside a role at all, and no scenario here exercises them. A future refactor that renames a task or swaps an `include_role` for an `import_role` somewhere in that chain could silently break `--tags images`/`--tags infra` without any scenario here noticing. There's no molecule scenario for this on purpose — a real integration scenario would need to converge through `deploy.yaml` itself (multi-host, real Docker install, `vars_prompt` handled non-interactively), which is a lot of cost for a narrow risk. Verify tag wiring manually instead with a quick dry run before trusting a change to it:

```sh
ansible-playbook deploy.yaml --tags images -e @secrets.yml --limit <host> -vvv | grep "TASK \["
```

and confirm the tasks you expect to see (and only those) show up in the output.
