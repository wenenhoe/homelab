# My Homelab

An Ansible-driven homelab: a small fleet of Ubuntu hosts, each running a set of Dockerized services behind a self-built **Caddy** reverse proxy, with **BIND9** as the authoritative internal DNS server. Everything — package installs, Docker Engine, DNS zones, TLS-terminating routes, and every application's config/directories — is generated and converged by a handful of Ansible playbooks and roles. There is no manual step on a target host beyond running `ansible-playbook`.

## Architecture

The lab is organized as a small group of hosts, each owning a subdomain of `lan.{{ main_domain }}` and running its own Caddy instance:

| Host | Role | Caddy domain |
| :--- | :--- | :--- |
| `services` | Core infra: DNS (BIND9), utility apps, DIUN update notifications | `svc.lan.{{ main_domain }}` |
| `play` | Game server hosting (Minecraft) | `play.lan.{{ main_domain }}` |
| `security` | Identity/SSO: LLDAP + Tinyauth forward-auth | `sec.lan.{{ main_domain }}` |
| `experiment` | Sandbox / test target | `test.lan.{{ main_domain }}` |

Every host in the `app_hosts` group runs its own Caddy instance and terminates TLS for its own `*.{{ caddy_domain }}` wildcard, using DNS-01 challenges via the DigitalOcean DNS provider. `services` additionally runs the single authoritative BIND9 instance for the whole lab: it scrapes every app host's declared DNS zones (via Ansible `hostvars`) and serves CNAME records that point each service back at its host's dynamic DNS target. Access to non-public apps is enforced by **Tinyauth**, which Caddy calls out to as a `forward_auth` step before proxying to the upstream container.

## Repository Layout

```
.
├── ansible/                 # All automation: playbooks, inventory, roles
│   ├── deploy.yaml          # Master playbook — full infra convergence
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
│       ├── compose/         # Reusable init/deploy tasks for one compose app
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

## Setup

Tooling is managed with [`uv`](https://docs.astral.sh/uv/getting-started/installation/) so no global Python/Ansible install is required.

- Install `uv`: see the [uv docs](https://docs.astral.sh/uv/getting-started/installation/)
- Install `pre-commit`:
  ```sh
  uv tool install pre-commit --with pre-commit-uv
  ```
- Install `ansible`:
  ```sh
  uv tool install ansible-core --with ansible
  ```
- Install the Docker Ansible collection (required by the `compose`, `caddy`, and `bind9` roles):
  ```sh
  ansible-galaxy collection install community.docker
  ```
- Install pre-commit hooks:
  ```sh
  pre-commit install
  ```
- Provide an SSH key at `~/.ssh/proxmox_vm_servers` (referenced by both inventories) with access to every target host.

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
| `deploy.yml` | `inventory.yaml` | The master playbook that imports other roles to configure the entire infrastructure. |
| `maintenance.yml` | `inventory.yaml` | Performs server maintenance activities such as package update. |
| `reset-network.yml` | `sos-inventory.yaml` | Resets network for entire infrastructure. |

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

## Linting & Pre-commit

`.pre-commit-config.yaml` wires up:

- `check-yaml`, `end-of-file-fixer`, `trailing-whitespace` — general hygiene
- [`gitleaks`](https://github.com/gitleaks/gitleaks) — secret scanning
- [`ansible-lint`](https://github.com/ansible/ansible-lint) — lints everything under `ansible/` (the `docker/` tree is excluded via `.ansible-lint`, since it's Compose files, not playbooks)
- [`dclint`](https://github.com/docker-compose-linter/pre-commit-dclint) — lints/auto-fixes every `compose*.yaml`

Run `pre-commit install` once after cloning so these run automatically on every commit.
