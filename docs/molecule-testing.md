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
| `caddy` | `default` | The custom DigitalOcean-DNS Caddy build (xcaddy from source) and deploy via `compose`. Slowest scenario — compiling Caddy typically takes a couple of minutes and needs real internet access for Go modules. |
| `bind9` | `default` | Zone-file aggregation/rendering/reload against a single instance that's a member of `app_hosts` itself (so it ends up serving DNS data about itself) — not a perfect topology match to the real multi-host setup, but exercises the real scraping/templating logic. |

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

## `molecule_helpers`

`ansible/roles/molecule_helpers/` isn't a role under test — it's a shared library of scaffolding for the other scenarios, so common setup doesn't get copy-pasted across every one of them:

| File | Used for |
| :--- | :--- |
| `playbooks/prepare_dind.yml` | The shared `prepare` playbook (see below). |
| `tasks/dind_vfs_storage_driver.yaml` | Forces the nested Docker daemon onto the `vfs` storage driver via `/etc/docker/daemon.json`. |
| `tasks/install_docker_api_requests.yaml` | Installs `python3-requests`, needed by `docker_volume`/`docker_host_info` and other `community.docker` modules that talk to the Docker API directly rather than through the CLI plugin. |
| `tasks/bootstrap_docker.yaml` | `include_role: docker` — for scenarios whose role-under-test assumes Docker is already installed (`compose`, `compose_app`, `caddy`, `bind9`), mirroring Play 1 of the real `deploy.yaml`. |
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

## Adding a new scenario

1. Copy an existing scenario directory (pick the closest match — e.g. `compose/molecule/default` for anything that deploys via Compose) rather than starting from scratch.
2. If the role-under-test assumes Docker is already running, point `converge.yml` at `molecule_helpers` for `bootstrap_docker.yaml` (and `resolve_compose_apps.yaml` if it uses `app_registry`/`compose_apps`) instead of duplicating that logic.
3. If the scenario needs Docker-in-Docker (privileged container, `cgroupns_mode: host`, `/sys/fs/cgroup` mounted), point `prepare` at `molecule_helpers/playbooks/prepare_dind.yml` rather than writing a new `prepare.yml` — unless, like `bind9`, the role's own tasks conflict with the shared one's `daemon.json` write.
4. Point `dependency.options` at the shared `role-requirements.yml`/`requirements.yml` instead of declaring collections locally.
5. Run `molecule test` locally before opening a PR — there's no CI wired up for this yet, so it's the only check that catches a broken scenario (including idempotence, not just `verify.yml`).

## What molecule scenarios can't catch: tag wiring

Every `converge.yml` above calls its role directly (`include_role: name: bind9`), never through `deploy.yaml`. That's the right choice for testing a role's actual logic in isolation, but it means the `images`/`infra` tag scheme (see [`deployment-flow.md`](deployment-flow.md#tags)) is structurally invisible to these scenarios — `deploy.yaml`'s own `Include <role>` wrapper tasks are what a run like `--tags images` actually depends on to reach anything inside a role at all, and no scenario here exercises them. A future refactor that renames a task or swaps an `include_role` for an `import_role` somewhere in that chain could silently break `--tags images`/`--tags infra` without any scenario here noticing. There's no molecule scenario for this on purpose — a real integration scenario would need to converge through `deploy.yaml` itself (multi-host, real Docker install, `vars_prompt` handled non-interactively), which is a lot of cost for a narrow risk. Verify tag wiring manually instead with a quick dry run before trusting a change to it:

```sh
ansible-playbook deploy.yaml --tags images -e @secrets.yml --limit <host> -vvv | grep "TASK \["
```

and confirm the tasks you expect to see (and only those) show up in the output.
