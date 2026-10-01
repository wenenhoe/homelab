# My Homelab

[![Renovate enabled](https://img.shields.io/badge/renovate-enabled-brightgreen.svg)](https://renovatebot.com)
[![Trivy scheduled scan](https://github.com/wenenhoe/homelab/actions/workflows/trivy-scheduled.yml/badge.svg)](https://github.com/wenenhoe/homelab/actions/workflows/trivy-scheduled.yml)

A small fleet of Ubuntu hosts running Dockerized services, fully converged by Ansible — package installs, DNS zones, TLS routes, and every app's config are generated on every run. There is no manual step on a target host beyond running `ansible-playbook`.

| Concern | Stack |
| :--- | :--- |
| Automation & networking | Ansible · Docker Compose · Caddy · BIND9 |
| Identity & secrets | OpenBao (Vault fork) · step-ca · LLDAP · Tinyauth |
| Data & ops | SeaweedFS · GitHub Actions · Molecule · Trivy · Renovate |

OpenTofu/Proxmox provisioning is in progress — see [`docs/projects/`](docs/projects/README.md).

## Architecture

The lab is organized as a small group of hosts, each owning a subdomain of `lan.{{ main_domain }}` and running its own Caddy instance:

| Host | Role | Caddy domain |
| :--- | :--- | :--- |
| `services` | Core infra: DNS (BIND9), utility apps, DIUN update notifications | `svc.lan.{{ main_domain }}` |
| `play` | Game server hosting (Minecraft) | `play.lan.{{ main_domain }}` |
| `security` | Identity/SSO: LLDAP + Tinyauth forward-auth, Beszel monitoring hub, OpenBao secrets store | `sec.lan.{{ main_domain }}` |
| `storage` | Backup target: SeaweedFS (self-hosted S3) receiving nightly `backup_agent` archives from every host, `cloud_sync` relay to R2/B2/OCI | `store.lan.{{ main_domain }}` |

Every `app_hosts` member runs its own Caddy instance and terminates TLS
for its own `*.{{ caddy_domain }}` wildcard via DNS-01 (DigitalOcean).
`services` additionally runs the lab's single authoritative BIND9
instance, scraping every app host's declared DNS zones and serving
CNAMEs back to each host's dynamic DNS target. Routes sit behind
**Tinyauth** forward-auth, backed by **LLDAP** as the directory, unless
a route sets `auth: false`. **Beszel** monitors host and container
health lab-wide, and **DIUN** watches deployed images and notifies over
Telegram on updates. Every host runs a `backup_agent` pushing
GPG-encrypted archives of its own apps' named volumes to **SeaweedFS** on
`storage` nightly, relayed further offsite by `cloud_sync` to R2/B2/OCI
— see [`docs/topics/disaster-recovery/backup.md`](docs/topics/disaster-recovery/backup.md).
Every secret in this repo is generated, cached, and rotated through
**OpenBao** on `security` — see
[`docs/topics/secrets/openbao.md`](docs/topics/secrets/openbao.md).

The rest of `docker/` is independently deployable Compose stacks
(dashboards, media-download tools, Minecraft, a link shortener, a
pastebin, PDF tools, a speed test and more), each just an `app_catalog`
entry plus a `docker/<app>/` directory — see
[`adding-an-app.md`](docs/topics/deploy/adding-an-app.md) to add one.
[`docs/architecture/system-overview.md`](docs/architecture/system-overview.md)
has a 10,000-ft diagram of the fleet.

## Hardware

Everything above runs on one Proxmox host: 6-core i5-9400, 32GB RAM, an NVMe boot/VM disk (1TB) plus a secondary 1TB HDD for backups.

## Where to go next

| I want to… | Read |
| :--- | :--- |
| Add an app | [`adding-an-app.md`](docs/topics/deploy/adding-an-app.md) |
| Follow what a `deploy.yaml` run does | [`deployment-flow.md`](docs/topics/deploy/deployment-flow.md) |
| Understand or restore a backup | [`backup.md`](docs/topics/disaster-recovery/backup.md) · [`restore.md`](docs/topics/disaster-recovery/restore.md) |
| Work with secrets | [`secrets.md`](docs/topics/secrets/secrets.md) · [`secrets-rotation.md`](docs/topics/secrets/secrets-rotation.md) |
| Understand CI | [`ci/pipeline.md`](docs/topics/engineering/ci/pipeline.md) |
| Find any other topic | [`docs/topics/README.md`](docs/topics/README.md) |
| Know why a design was chosen | [decisions](docs/decisions/README.md) |
| See what is planned or in flight | [`project-planning.md`](docs/project-planning.md) · [projects](docs/projects/README.md) |
| Work out where a new doc goes | [`docs/README.md`](docs/README.md) |
| Start as an agent | [`AGENTS.md`](AGENTS.md) |

CI keeps the docs in step with the code — see
[`ci/doc-checks.md`](docs/topics/engineering/ci/doc-checks.md).

## Repository Layout

```
.
├── .config/                 # Tool configs (lint/format/pre-commit)
├── .github/                 # CI workflows, PR-check scripts, Renovate config
├── ansible/                 # All automation: playbooks, inventory, roles
├── docker/                  # One directory per application
├── docs/                    # Topic docs, decisions, projects, diagrams
├── tools/                   # Controller-side Python: cloud-credential minting, OpenBao/Vault utilities
├── AGENTS.md                # Where an agent starts: the doc workflow's rules and stop conditions
└── pyproject.toml / uv.lock # uv project files (must stay at repo root)
```

Each app under `docker/<app>/` holds its `compose.yaml` (or
`compose.yaml.j2` — see [`adding-an-app.md`](docs/topics/deploy/adding-an-app.md))
plus a `configs/` directory of Jinja2 templates that Ansible renders
onto the target host — nothing is hand-authored on the servers
themselves. `docker/molecule-dind/` is the one exception: it's Molecule
test scaffolding, not a deployed app.

## Setup

Tooling is managed with [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
as a project dependency manager (`pyproject.toml` + `uv.lock`).
`ansible-core`, the `docker` Python SDK, `molecule`, `molecule-plugins`,
and `pre-commit` all live in one shared `.venv/`.

`ansible-core` is used instead of the full `ansible` metapackage — the
two collections this repo needs (`community.docker`, `ansible.posix`)
are declared explicitly in `ansible/requirements.yml` for an exact,
reproducible dependency set.

- Install `uv`: see the [uv docs](https://docs.astral.sh/uv/getting-started/installation/)
- Install everything (creates `.venv/` from `pyproject.toml`/`uv.lock`):
   ```sh
  uv sync
   ```
- Activate the environment (do this once per shell session):
   ```sh
  source .venv/bin/activate
   ```
  Alternatively, prefix any individual command with `uv run` instead of activating (e.g. `uv run molecule test`).
- Install the collections this repo needs:
   ```sh
  ansible-galaxy collection install -r ansible/requirements.yml
   ```
- Install pre-commit's git hooks:
   ```sh
   pre-commit install
   ```
   This installs both the commit-time and push-time hooks; what runs when
   is in [`pre-commit.md`](docs/topics/engineering/pre-commit.md).
- Provide an SSH key at `~/.ssh/proxmox_vm_servers` (referenced by both inventories) with access to every target host.
- Install a native `bao` CLI (needed for `tools/openbao_utils/bao_session.py` and anything else that talks to OpenBao from here) - a personal, one-time step, not Ansible-managed, since this machine's own OS can't be assumed the way a `managed_hosts` member's can:
   ```sh
   version=$(python3 -c "import yaml; print(yaml.safe_load(open('ansible/roles/openbao_cli/defaults/main.yaml'))['openbao_cli_version'])")
   sha256=$(python3 -c "import yaml; print(yaml.safe_load(open('ansible/roles/openbao_cli/defaults/main.yaml'))['openbao_cli_deb_sha256'])")
   curl -LO "https://github.com/openbao/openbao/releases/download/v${version}/openbao_${version}_linux_amd64.deb"
   echo "${sha256}  openbao_${version}_linux_amd64.deb" | sha256sum -c
   sudo dpkg -i "openbao_${version}_linux_amd64.deb"
   sudo systemctl disable --now openbao.service
   sudo systemctl mask openbao.service
   sudo rm -rf /opt/openbao /etc/openbao
   ```
  Reads the version and checksum straight out of `ansible/roles/openbao_cli`'s own defaults - the same values that role installs on `security` - so there's no second, hand-copied pin here to drift out of sync when that role's own gets bumped. The last four commands undo the standalone-server scaffolding the `.deb`'s installer sets up unconditionally, which this machine has no use for (see that role's `tasks/main.yaml`'s own comment on why the removal runs on every install, not just the first).
- Before your first `deploy.yaml` run, fill in every value Ansible can't
  generate itself (DigitalOcean API key, Let's Encrypt email, Diun's
  Telegram token/chat ID, and a few others):
   ```sh
  cd tools && python3 -m openbao_utils.bootstrap
   ```
  Safe to re-run — only fills in what's missing. See
  [`docs/topics/secrets/secrets.md`](docs/topics/secrets/secrets.md).

Docker must be running locally for `molecule` (each role's scenario spins up and tears down real containers).

## Basic Commands

### `ansible` commands

- Test connectivity:
  ```sh
  ansible all -m ping
  ```
- Select hosts to run (single/multiple):
  ```sh
  ansible-playbook playbooks/deploy.yaml --limit services
  ansible-playbook playbooks/deploy.yaml --limit services,play
  ```
- Dry run:
  ```sh
  ansible-playbook playbooks/deploy.yaml --check --diff
  ```
- Check what a host resolves to (`resolved_apps` is `compose_apps` merged over `app_catalog`):
  ```sh
  ansible localhost -i inventory/inventory.yaml -m ansible.builtin.debug -a "var=hostvars['services'].resolved_apps"
  ```

Tag-based runs (skip provisioning, pull only images, re-render
infra-only) are in [`docs/topics/deploy/ansible.md`](docs/topics/deploy/ansible.md#tag-based-commands).

### `docker` commands

- Stop and remove all containers on a host:
  ```sh
  docker stop $(docker ps -q) && docker rm $(docker ps -aq)
  ```

## Testing

Roles are tested individually with
[Molecule](https://ansible.readthedocs.io/projects/molecule/), co-located
at `ansible/roles/<role>/molecule/<scenario>/`:

```sh
cd ansible/roles/apt
molecule test              # default scenario
molecule test -s volumes   # named scenario (cd ansible/roles/compose first)
```

The scenario matrix and how to add one are in
[`molecule-testing.md`](docs/topics/engineering/molecule-testing.md).

Plain controller-side Python (`tools/cloud_credentials/`,
`tools/openbao_utils/`, `ansible/molecule-coverage/molecule_cov/`, the R2
read-watcher) is tested separately with [pytest](https://docs.pytest.org/),
from the repo root. Every provider HTTP call and `rclone` invocation is
mocked, so no network access or real cloud credentials are needed:

```sh
pytest ansible/tests/ tools/tests/ -v
```

On every PR CI also boot-tests each changed compose app and checks deploy
ordering, and Trivy scans run on a schedule — see
[`ci/pipeline.md`](docs/topics/engineering/ci/pipeline.md).

## Linting & Pre-commit

Most hooks run at commit time; `ansible-lint` runs at push time.
`pre-commit run --all-files` runs the commit-time hooks by hand, and CI
enforces the same checks on every PR whether or not hooks are installed
locally. The hook list, what runs when, and where each tool's config
lives are in [`pre-commit.md`](docs/topics/engineering/pre-commit.md).
