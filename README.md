# My Homelab

An Ansible-driven homelab: a small fleet of Ubuntu hosts, each running a set of Dockerized services behind a **Caddy** reverse proxy, with **BIND9** as the authoritative internal DNS server. Package installs, Docker Engine, DNS zones, TLS-terminating routes, and every application's config/directories are generated and converged by a handful of Ansible playbooks and roles. There is no manual step on a target host beyond running `ansible-playbook`.

## Architecture

The lab is organized as a small group of hosts, each owning a subdomain of `lan.{{ main_domain }}` and running its own Caddy instance:

| Host | Role | Caddy domain |
| :--- | :--- | :--- |
| `services` | Core infra: DNS (BIND9), utility apps, DIUN update notifications | `svc.lan.{{ main_domain }}` |
| `play` | Game server hosting (Minecraft) | `play.lan.{{ main_domain }}` |
| `security` | Identity/SSO: LLDAP + Tinyauth forward-auth, Beszel monitoring hub | `sec.lan.{{ main_domain }}` |
| `experiment` | Sandbox / test target | `test.lan.{{ main_domain }}` |

Every host in the `app_hosts` group runs its own Caddy instance and terminates TLS for its own `*.{{ caddy_domain }}` wildcard, using DNS-01 challenges via the DigitalOcean DNS provider. `services` additionally runs the single authoritative BIND9 instance for the whole lab: it scrapes every app host's declared DNS zones (via Ansible `hostvars`) and serves CNAME records that point each service back at its host's dynamic DNS target. Access to non-public apps is enforced by **Tinyauth**, which Caddy calls out to as a `forward_auth` step before proxying to the upstream container.

## Repository Layout

```
.
├── ansible/                 # All automation: playbooks, inventory, roles
│   ├── deploy.yaml          # Master playbook — full infra convergence
│   ├── cleanup.yaml         # Tear down stacks no longer in a host's compose_apps
│   ├── maintenance.yaml     # apt + firmware updates
│   ├── reset-network.yaml   # netplan re-apply
│   ├── inventory.yaml       # Hosts reachable over DNS (day-to-day use)
│   ├── sos-inventory.yaml   # Hosts reachable by raw IP (recovery use)
│   ├── ansible.cfg
│   ├── group_vars/all.yaml  # Global vars + the app_registry
│   ├── host_vars/*.yaml     # Per-host compose_apps, caddy_domain, dns_zones
│   └── roles/
│       ├── apt/             # System package updates
│       ├── fwupd/           # Firmware updates
│       ├── docker/          # Docker Engine install
│       ├── compose/         # Reusable init/deploy/cleanup tasks for one compose app
│       ├── compose_app/     # Batch-drives `compose/` for every non-infra app
│       ├── caddy/           # Renders Caddyfile, builds custom image, deploys
│       └── bind9/           # Renders zone files, deploys, rewires host DNS
├── docker/                  # One directory per application
│   ├── caddy/               # compose.yaml + env template for the proxy
│   ├── bind9/               # compose.yaml + env template for DNS
│   └── <app>/               # compose.yaml + configs/scripts per app
└── docs/                    # Deep dives — see below
```

Each app under `docker/<app>/` holds its `compose.yaml` plus a `configs/` directory of Jinja2 templates (`.env` files, app config files) that Ansible renders onto the target host — the `docker/` tree is the single source of truth for what gets deployed; nothing is hand-authored on the servers themselves.

## Further Reading

| Doc | Covers |
| :--- | :--- |
| [`docs/deployment-flow.md`](docs/deployment-flow.md) | The 4-play `deploy.yaml` sequence, the role responsibilities, and the `app_registry` pattern that drives per-host config resolution. |
| [`docs/volumes.md`](docs/volumes.md) | The named-volume storage architecture: registry `volumes:` field, one-time migration from bind mounts, staging + seeding Ansible-rendered configs, and backward compatibility with plain bind-mounted apps. |
| [`docs/bind9.md`](docs/bind9.md) | How the internal DNS zones are aggregated, rendered, and reloaded without spurious restarts. |
| [`docs/caddy.md`](docs/caddy.md) | The custom DigitalOcean-DNS Caddy build, Caddyfile generation, and Tinyauth forward-auth wiring. |
| [`docs/beszel.md`](docs/beszel.md) | Hub/agent monitoring setup, the WebSocket connection model, and the one-time KEY/TOKEN bootstrap sequence. |
| [`docs/adding-an-app.md`](docs/adding-an-app.md) | Step-by-step: wiring a new Compose app into the `app_registry` and a host's `compose_apps`. |
| [`docs/host-vars.md`](docs/host-vars.md) | Field-by-field reference for `host_vars/<host>.yaml`: `caddy_domain`, `compose_apps`, per-host alias vars, `dns_ddns_target`/`dns_zones`. |
| [`docs/cleanup.md`](docs/cleanup.md) | How `cleanup.yaml` finds stacks orphaned from `compose_apps`, the keep-vs-delete content policy, and dry-running a cleanup pass. |
| [`docs/molecule-testing.md`](docs/molecule-testing.md) | The full per-role/per-scenario Molecule matrix, what `molecule_helpers` shares across scenarios, the Docker-in-Docker `vfs` storage-driver quirk, and how to add a new scenario. |

## Setup

Tooling is managed with [`uv`](https://docs.astral.sh/uv/getting-started/installation/) as a project dependency manager (`pyproject.toml` + `uv.lock`), not via `uv tool install`. Everything — `ansible-core`, the `docker` Python SDK, `molecule`, `molecule-plugins`, `pre-commit` — lives in one shared, reproducible `.venv/`, avoiding the duplicate-collection issues that come from installing `ansible-core` into multiple separate tool venvs.

`ansible-core` is used deliberately instead of the full `ansible` metapackage. `ansible` bundles hundreds of community collections this repo doesn't use; the two it actually needs (`community.docker`, `ansible.posix`) are declared explicitly in `ansible/requirements.yml` instead, so the dependency set is exact and reproducible.

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
- Provide an SSH key at `~/.ssh/proxmox_vm_servers` (referenced by both inventories) with access to every target host.

Docker must be running locally for `molecule` (each role's scenario spins up and tears down real containers).

## Inventory

Two inventories exist for two different situations:

| Inventory | Used by | Host addressing | Purpose |
| :--- | :--- | :--- | :--- |
| `inventory.yaml` | `deploy.yaml`, `maintenance.yaml` | `<host>.{{ ddns_domain }}` (DNS name) | Day-to-day operation once DNS is up |
| `sos-inventory.yaml` | `reset-network.yaml` | Static `192.168.20.x` IPs | Recovery path when DNS/network is down |

`inventory.yaml` also defines two groups the roles depend on directly:

- **`app_hosts`** — every host that owns `compose_apps` / `dns_zones` / `caddy_domain`; the `bind9` role iterates this group's `hostvars` to build DNS zone files.
- **`dns`** — the single host (`services`) the `bind9` role actually runs on.

## Ansible Playbooks

| Playbook File | Inventory | Description |
| :--- | :--- | :--- |
| `deploy.yaml` | `inventory.yaml` | Master playbook — converges the entire infrastructure: Docker install, Caddy, BIND9, and every application. See [`docs/deployment-flow.md`](docs/deployment-flow.md). |
| `cleanup.yaml` | `inventory.yaml` | Tears down stacks that are deployed/running on a host but no longer listed in its `compose_apps`, with a keep/delete policy for their on-disk content and named Docker volumes. See [`docs/cleanup.md`](docs/cleanup.md). |
| `maintenance.yaml` | `inventory.yaml` | Server maintenance: `apt` upgrade + reboot-if-required, `fwupd` firmware updates + reboot-if-required. |
| `reset-network.yaml` | `sos-inventory.yaml` | Re-applies `netplan` on every host; used when a host's network config needs a clean reset. |

## Basic Commands

### `ansible` commands

- Test connectivity:
  ```sh
  ansible all -m ping
  ```
- Select hosts to run (single/multiple):
  ```sh
  ansible-playbook deploy.yaml --limit test
  ansible-playbook deploy.yaml --limit test,prod
  ```
- Dry run:
  ```sh
  ansible-playbook deploy.yaml --check --diff
  ```
- Filter roles by tags (e.g. skip the Docker Engine install on hosts that already have it):
  ```sh
  ansible-playbook deploy.yaml --skip-tags "initial-setup"
  ```
- Pull-only image refresh without a full converge:
  ```sh
  ansible-playbook deploy.yaml --tags "pull-docker-images"
  ```
- Check target host variables (e.g. to confirm the resolved `compose_apps`/`app_registry` merge for a host):
  ```sh
  ansible-inventory -i inventory.yaml --host experiment
  ```

### `docker` commands

- Stop and remove all containers on a host:
  ```sh
  docker stop $(docker ps -q) && docker rm $(docker ps -aq)
  ```

## Applications

Everything routed through Caddy sits behind **Tinyauth** forward-auth by default (per-route `auth: false` opts out — e.g. Cobalt, Dashy, OpenSpeedTest, LLDAP's own UI, Beszel's hub), backed by **LLDAP** as the directory. **DIUN** watches deployed images and notifies over Telegram when updates are available. **Beszel** monitors host and container health across every `app_hosts` member, with its hub on `security` and an agent on each host — see [`docs/beszel.md`](docs/beszel.md). The rest of `docker/` is a set of independently deployable Compose stacks (dashboards, media/download tools, a Minecraft server, link shortener, pastebin, web terminal, etc.) — each one just an entry in `app_registry` plus a `docker/<app>/` directory of its `compose.yaml` and config templates. See [`docs/adding-an-app.md`](docs/adding-an-app.md) to add a new one.

## Testing

Roles are tested individually with [Molecule](https://ansible.readthedocs.io/projects/molecule/), using the co-located convention: each role's scenario(s) live at `ansible/roles/<role>/molecule/<scenario>/`. Roles are brought up in Docker containers, converged, verified, then re-converged to check idempotence.

Run a single role's default scenario:

```sh
cd ansible/roles/apt
molecule test
```

`fwupd` has no scenario — it talks to real firmware/LVFS hardware, which a container can't meaningfully simulate.

Most other roles have `default` plus one or more named scenarios covering a specific branch or edge case — `compose`, for example, also has `volumes`, `scripts`, `build`, and `cleanup`. Run a non-default scenario with `-s`:

```sh
cd ansible/roles/compose
molecule test -s volumes
```

Shared setup that would otherwise be duplicated across scenarios — the Docker-in-Docker `prepare` playbook, bootstrapping the `docker` role, resolving `compose_apps`, Galaxy dependencies — lives once in `ansible/roles/molecule_helpers/` and is referenced from each scenario's `molecule.yml`/`converge.yml` instead of copy-pasted. See [`docs/molecule-testing.md`](docs/molecule-testing.md) for the full scenario matrix and how to add a new one.

## Linting & Pre-commit

`.pre-commit-config.yaml` wires up:

- `check-yaml`, `end-of-file-fixer`, `trailing-whitespace` — general hygiene
- [`gitleaks`](https://github.com/gitleaks/gitleaks) — secret scanning
- [`ansible-lint`](https://github.com/ansible/ansible-lint) — lints everything under `ansible/` (the `docker/` tree is excluded via `.ansible-lint`, since it's Compose files, not playbooks)
- [`dclint`](https://github.com/docker-compose-linter/pre-commit-dclint) — lints/auto-fixes every `compose*.yaml`

Run `pre-commit install` once after cloning so these run automatically on every commit.
