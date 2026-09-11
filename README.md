# My Homelab

[![Renovate enabled](https://img.shields.io/badge/renovate-enabled-brightgreen.svg)](https://renovatebot.com)
[![Trivy scheduled scan](https://github.com/wenenhoe/homelab/actions/workflows/trivy-scheduled.yml/badge.svg)](https://github.com/wenenhoe/homelab/actions/workflows/trivy-scheduled.yml)

A small fleet of Ubuntu hosts running Dockerized services, fully converged by Ansible — package installs, DNS zones, TLS routes, and every app's config are generated on every run. There is no manual step on a target host beyond running `ansible-playbook`.

**Automation & networking:** Ansible · Docker Compose · Caddy · BIND9

**Identity & secrets:** OpenBao (Vault fork) · step-ca · LLDAP · Tinyauth

**Data & ops:** SeaweedFS · GitHub Actions · Molecule · Trivy · Renovate

OpenTofu/Proxmox provisioning is in progress — see [`docs/projects/`](docs/projects/README.md).

## Architecture

The lab is organized as a small group of hosts, each owning a subdomain of `lan.{{ main_domain }}` and running its own Caddy instance:

| Host | Role | Caddy domain |
| :--- | :--- | :--- |
| `services` | Core infra: DNS (BIND9), utility apps, DIUN update notifications | `svc.lan.{{ main_domain }}` |
| `play` | Game server hosting (Minecraft) | `play.lan.{{ main_domain }}` |
| `security` | Identity/SSO: LLDAP + Tinyauth forward-auth, Beszel monitoring hub, OpenBao secrets store | `sec.lan.{{ main_domain }}` |
| `storage` | Offsite-backup target: SeaweedFS (self-hosted S3) receiving nightly `backup_agent` archives from every host, `cloud_sync` relay to R2/B2/OCI | `store.lan.{{ main_domain }}` |

Every `app_hosts` member runs its own Caddy instance and terminates TLS
for its own `*.{{ caddy_domain }}` wildcard via DNS-01 (DigitalOcean).
`services` additionally runs the lab's single authoritative BIND9
instance, scraping every app host's declared DNS zones and serving
CNAMEs back to each host's dynamic DNS target. Non-public apps sit behind
**Tinyauth** forward-auth. Every host also runs a `backup_agent` instance
pushing GPG-encrypted archives of its own apps' named volumes to
`storage` nightly — see [`docs/disaster-recovery.md`](docs/disaster-recovery.md).

## Project Management

- **Decisions** — non-obvious design choices become numbered [ADRs](docs/decisions/README.md).
- **Multi-stage work** — tracked in a [project doc](docs/projects/README.md) until every stage is done, at which point its rationale and behavior get promoted into an ADR or topic doc and the project doc is deleted.
- **Drift enforcement** — CI checks that docs stay in sync with the code, the playbook/role reference tables match what's on disk, and every cross-file link resolves.
- **Testing** — Molecule role tests, boot-testing, and scheduled Trivy scans.

## Repository Layout

```
.
├── .config/                 # Tool configs (lint/format/pre-commit)
├── .github/                 # CI workflows, PR-check scripts, Renovate config — see docs/ci.md
├── ansible/                 # All automation: playbooks, inventory, roles — see docs/ansible.md
├── docker/                  # One directory per application
├── docs/                    # Deep dives — see docs/README.md
└── pyproject.toml / uv.lock # uv project files (must stay at repo root)
```

Each app under `docker/<app>/` holds its `compose.yaml` (or
`compose.yaml.j2` — see [`adding-an-app.md`](docs/adding-an-app.md))
plus a `configs/` directory of Jinja2 templates that Ansible renders
onto the target host — nothing is hand-authored on the servers
themselves. `docker/molecule-dind/` is the one exception: it's Molecule
test scaffolding, not a deployed app.

## Further Reading

See [`docs/README.md`](docs/README.md) for how these docs are
organized and its full categorized index — start there if you're
looking for where something new should go, or for any specific topic.

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
   `.pre-commit-config.yaml` at the repo root is a symlink to
   `.config/.pre-commit-config.yaml` (config lives under `.config/`, but
   `pre-commit` only ever looks for its own config at the repo root by
   default — no `-c` flag needed for this or `pre-commit run`, and
   nothing lints the symlink itself, only real `.yaml` files). Installs
   both the `pre-commit` and `pre-push` git hooks in one step
   (`default_install_hook_types` in the config) — most hooks run at
   commit time, `ansible-lint` runs at push time since it always re-lints
   the whole `ansible/` tree rather than just what changed. To run
   everything manually regardless of stage: `pre-commit run --all-files
   --hook-stage pre-commit` and `... --hook-stage pre-push`.
- Provide an SSH key at `~/.ssh/proxmox_vm_servers` (referenced by both inventories) with access to every target host.
- Before your first `deploy.yaml` run, fill in every value Ansible can't
  generate itself (DigitalOcean API key, Let's Encrypt email, Diun's
  Telegram token/chat ID, and a few others):
   ```sh
  python3 ansible/bootstrap_secrets.py
   ```
  Safe to re-run — only fills in what's missing. See
  [`docs/secrets.md`](docs/secrets.md).

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
- Check target host variables (e.g. to confirm the resolved `compose_apps`/`app_registry` merge for a host):
  ```sh
  ansible-inventory -i inventory/inventory.yaml --host services
  ```

Tag-based runs (skip provisioning, pull only images, re-render
infra-only) are in [`docs/ansible.md`](docs/ansible.md#tag-based-commands).

### `docker` commands

- Stop and remove all containers on a host:
  ```sh
  docker stop $(docker ps -q) && docker rm $(docker ps -aq)
  ```

## Applications

Everything routed through Caddy sits behind **Tinyauth** forward-auth by
default (per-route `auth: false` opts out, e.g. Cobalt, Dashy,
Beszel's hub, and Uptime Kuma), backed by **LLDAP** as the directory. **DIUN** watches
deployed images and notifies over Telegram on updates. **Beszel**
monitors host/container health lab-wide — see
[`docs/beszel.md`](docs/beszel.md). Every host runs a **`backup_agent`**
pushing GPG-encrypted archives to **SeaweedFS** on `storage` nightly —
see [`docs/disaster-recovery.md`](docs/disaster-recovery.md), relayed
further offsite by **`cloud_sync`** to R2/B2/OCI. Every secret in this
repo is generated, cached, and rotated through **OpenBao** on
`security` — see [`docs/openbao.md`](docs/openbao.md). The rest of
`docker/` is independently deployable Compose stacks (dashboards, media
tools, Minecraft, link shortener, pastebin, web terminal, etc.), each
just an `app_registry` entry plus a `docker/<app>/` directory (see
Further Reading above to add one).

## Testing

Roles are tested individually with
[Molecule](https://ansible.readthedocs.io/projects/molecule/), co-located
at `ansible/roles/<role>/molecule/<scenario>/`.

```sh
cd ansible/roles/apt
molecule test              # default scenario
molecule test -s volumes   # named scenario (cd ansible/roles/compose first)
```

See [`docs/molecule-testing.md`](docs/molecule-testing.md) for the full
scenario matrix and how to add one.

Plain controller-side Python (`ansible/cloud_credentials/`,
`ansible/molecule-coverage/molecule_cov/`, `bootstrap_secrets.py`,
`audit_secrets.py`, the R2 read-watcher) is tested separately with
[pytest](https://docs.pytest.org/), from `ansible/`:

```sh
cd ansible
pytest tests/ -v
```

Every provider HTTP call and `rclone` invocation is mocked — no
network access or real cloud credentials needed. See
[`docs/ci.md`](docs/ci.md) for how this runs in CI.

## Linting & Pre-commit

`.config/.pre-commit-config.yaml` wires up:

- `check-yaml`, `end-of-file-fixer`, `trailing-whitespace` — general hygiene
- [`gitleaks`](https://github.com/gitleaks/gitleaks) — secret scanning
- [`yamllint`](https://github.com/adrienverge/yamllint) — strict YAML style checks (`.config/.yamllint`)
- [`dclint`](https://github.com/docker-compose-linter/pre-commit-dclint) — lints/auto-fixes every `compose*.yaml`
- [`hadolint`](https://github.com/hadolint/hadolint) — lints every `Dockerfile`, via its Docker-image variant
- [`markdownlint-cli2`](https://github.com/DavidAnson/markdownlint-cli2) — lints every `*.md`
- [`ruff`](https://github.com/astral-sh/ruff-pre-commit) — lints (auto-fixing) and formats every `*.py`

All of the above run at commit time. [`ansible-lint`](https://github.com/ansible/ansible-lint)
(lints `ansible/`; `docker/` excluded, it's Compose files not playbooks)
runs at **push** time instead — it always re-lints the whole `ansible/`
tree regardless of what changed, so it's too slow to pay on every commit.

All tool configs live under `.config/` (each hook is passed an explicit
`-c` flag, since these tools don't auto-discover configs there by
default). `ansible-lint` also gets `--project-dir ansible`, since it
resolves `roles_path` relative to cwd rather than the config file.
`ruff` is one exception — its config lives in `pyproject.toml` at
the repo root, which it finds on its own, so no `-c` flag or
`.config/` entry exists for it. `hadolint` is the other: its accepted-risk
findings are per-file, so they're justified inline with
`# hadolint ignore=DLxxxx # reason` comments next to the line they apply
to (`docker/caddy/Dockerfile`, `docker/molecule-dind/Dockerfile`) rather
than a repo-wide `.config/` ignore list.

Run `pre-commit install` once after
cloning. CI enforces the same checks on every PR regardless of whether
hooks are installed locally — see [`docs/ci.md`](docs/ci.md).
