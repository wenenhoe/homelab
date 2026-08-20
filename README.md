# My Homelab

An Ansible-driven homelab: a small fleet of Ubuntu hosts, each running a set of Dockerized services behind a **Caddy** reverse proxy, with **BIND9** as the authoritative internal DNS server. Package installs, Docker Engine, DNS zones, TLS-terminating routes, and every application's config/directories are generated and converged by a handful of Ansible playbooks and roles. There is no manual step on a target host beyond running `ansible-playbook`.

## Architecture

The lab is organized as a small group of hosts, each owning a subdomain of `lan.{{ main_domain }}` and running its own Caddy instance:

| Host | Role | Caddy domain |
| :--- | :--- | :--- |
| `services` | Core infra: DNS (BIND9), utility apps, DIUN update notifications | `svc.lan.{{ main_domain }}` |
| `play` | Game server hosting (Minecraft) | `play.lan.{{ main_domain }}` |
| `security` | Identity/SSO: LLDAP + Tinyauth forward-auth, Beszel monitoring hub | `sec.lan.{{ main_domain }}` |
| `storage` | Offsite-backup target: SeaweedFS (self-hosted S3) receiving nightly `backup_agent` archives from every host | `store.lan.{{ main_domain }}` |

Every `app_hosts` member runs its own Caddy instance and terminates TLS
for its own `*.{{ caddy_domain }}` wildcard via DNS-01 (DigitalOcean).
`services` additionally runs the lab's single authoritative BIND9
instance, scraping every app host's declared DNS zones and serving
CNAMEs back to each host's dynamic DNS target. Non-public apps sit behind
**Tinyauth** forward-auth. Every host also runs a `backup_agent` instance
pushing GPG-encrypted archives of its own apps' named volumes to
`storage` nightly — see [`docs/disaster-recovery.md`](docs/disaster-recovery.md).

## Repository Layout

```
.
├── .config/                 # Tool configs (lint/format/pre-commit)
│   ├── .ansible-lint
│   ├── .yamllint
│   ├── .dclintrc
│   ├── .pre-commit-config.yaml
│   └── molecule/config.yml
├── ansible/                 # All automation: playbooks, inventory, roles
│   ├── ansible.cfg
│   ├── requirements.yml
│   ├── bootstrap_secrets.py # Interactive prompt for values Ansible can't generate itself
│   ├── molecule-test-all.sh # Runs every role's molecule scenarios; see docs/molecule-testing.md
│   ├── molecule-coverage/   # Task/loop/branch coverage tool for molecule scenarios
│   ├── files/                   # Non-secret static files (e.g. the backup GPG public key)
│   ├── playbooks/
│   │   ├── deploy.yaml           # Master playbook — full infra convergence
│   │   ├── cleanup.yaml          # Tear down stacks no longer in a host's compose_apps
│   │   ├── maintenance.yaml      # apt + firmware updates
│   │   ├── reset-network.yaml    # netplan re-apply
│   │   ├── restore.yaml          # Stage 1 DR: restore one app's volume(s)
│   │   ├── volume-file-rm.yaml   # Remove specific named file(s) from a volume in place
│   │   ├── volume-reset.yaml     # Wipe a volume and recreate it from seeded config only
│   │   ├── bootstrap-secrets.yaml# Leading play deploy.yaml/restore.yaml import for secrets
│   │   └── ci_boot_test.yaml     # CI-only: seeds one app for the compose boot-test job
│   ├── inventory/
│   │   ├── inventory.yaml                     # Hosts reachable over DNS (day-to-day use)
│   │   ├── sos-inventory.yaml                 # Hosts reachable by raw IP (recovery use)
│   │   ├── ci-deploy-ordering-inventory.yaml  # CI-only: see docs/ci.md
│   │   ├── group_vars/
│   │   │   ├── all/main.yaml             # Global vars (timezone, DNS domains, Beszel/backup secrets)
│   │   │   ├── all/app_registry.yaml     # The app registry (see below)
│   │   │   └── all/secrets_registry.yaml # Declares every generated/manual secret; see docs/secrets.md
│   │   └── host_vars/*.yaml     # Per-host compose_apps, caddy_domain, dns_zones
│   ├── ci-inventory/        # CI-only inventory/vars for the compose-boot-test job
│   └── roles/
│       ├── apt/             # System package updates
│       ├── fwupd/           # Firmware updates
│       ├── docker/          # Docker Engine install
│       ├── qemu_guest_agent/# Installs qemu-guest-agent for Proxmox VM integration
│       ├── compose/         # Reusable init/deploy/cleanup tasks for one compose app
│       ├── compose_app/     # Batch-drives `compose/` for every non-infra app
│       ├── caddy/           # Renders Caddyfile, builds custom image, deploys
│       ├── caddy_cert_expiry/# Alerts if Caddy's live-serving cert is expiring/unreachable
│       ├── bind9/           # Renders zone files, deploys, rewires host DNS
│       ├── seaweedfs_bucket/# Ensures the offsite-backup S3 bucket exists on `storage`
│       ├── lldap_bootstrap/ # Automates lldap's `observer` account for tinyauth's LDAP bind
│       ├── step_ca_client/  # Shared prerequisite: caches step-ca's root cert on the host
│       ├── lldap_cert/      # Issues/renews lldap's LDAPS cert from step-ca
│       ├── telegram_notify/ # Shared library role: direct-curl Telegram alert unit
│       ├── tinyauth_ca_trust/# Builds the CA bundle tinyauth needs to trust step-ca-issued certs
│       ├── tinyauth/        # Molecule-only: deploys tinyauth for real in its own scenario
│       ├── backup_agent/    # Per-host offsite backup aggregation (stage 1 DR)
│       ├── cloud_sync/      # Offsite replication of SeaweedFS archives to R2/B2/OCI
│       ├── restore/         # Restores a decrypted offsite archive back to a named volume
│       ├── secrets/         # Generates/validates every entry in secrets_registry.yaml
│       └── molecule_helpers/# Shared Molecule test fixtures/setup, not deployed
├── docker/                  # One directory per application
│   ├── caddy/               # compose.yaml + env template for the proxy
│   ├── bind9/               # compose.yaml.j2 — timezone templated in, no separate .env
│   ├── seaweedfs/           # compose.yaml + S3 identity config for the offsite-backup target
│   ├── molecule-dind/       # Not an app — pre-baked DinD image for Molecule, see docs/molecule-testing.md
│   └── <app>/               # compose.yaml (or compose.yaml.j2) + configs/scripts per app
├── pyproject.toml / uv.lock # uv project files (must stay at repo root)
└── docs/                    # Deep dives — see below
```

Each app under `docker/<app>/` holds its `compose.yaml` (or
`compose.yaml.j2` — see [`adding-an-app.md`](docs/adding-an-app.md))
plus a `configs/` directory of Jinja2 templates that Ansible renders
onto the target host — nothing is hand-authored on the servers
themselves. `docker/molecule-dind/` is the one exception: it's Molecule
test scaffolding, not a deployed app.

## Further Reading

### Architecture & workflow

| Doc | Covers |
| :--- | :--- |
| [`docs/deployment-flow.md`](docs/deployment-flow.md) | The `deploy.yaml` play sequence, role responsibilities, `app_registry`. |
| [`docs/volumes.md`](docs/volumes.md) | Named-volume storage: bind-mount migration, config seeding. |
| [`docs/host-vars.md`](docs/host-vars.md) | `host_vars/<host>.yaml` field reference. |
| [`docs/adding-an-app.md`](docs/adding-an-app.md) | Wiring a new Compose app into the registry. |
| [`docs/vm-provisioning.md`](docs/vm-provisioning.md) | OpenTofu-driven Proxmox VM provisioning: VMID/VLAN/IP scheme, OPNsense, migration staging. |

### Per-app infra

| Doc | Covers |
| :--- | :--- |
| [`docs/bind9.md`](docs/bind9.md) | Internal DNS zone aggregation and rendering. |
| [`docs/caddy.md`](docs/caddy.md) | Custom Caddy build, Caddyfile generation, Tinyauth wiring. |
| [`docs/beszel.md`](docs/beszel.md) | Hub/agent monitoring, KEY/TOKEN bootstrap. |
| [`docs/telegram-notifications.md`](docs/telegram-notifications.md) | Bot/topic scheme shared by diun, Beszel, backups, and cert-renewal alerts. |
| [`docs/lldap.md`](docs/lldap.md) | LDAPS cert lifecycle via step-ca and a systemd renewal timer; bootstrapping the observer account tinyauth binds as. |
| [`docs/step-ca.md`](docs/step-ca.md) | Internal PKI: bootstrap, provisioner claims, requesting a cert. |
| [`docs/wastebin.md`](docs/wastebin.md) | Custom wastebin image: adding a static `wget` to a `FROM scratch` base for healthchecks. |
| [`docs/qemu-guest-agent.md`](docs/qemu-guest-agent.md) | Installing `qemu-guest-agent` for Proxmox VM integration. |

### Operations

| Doc | Covers |
| :--- | :--- |
| [`docs/cleanup.md`](docs/cleanup.md) | Removing stacks orphaned from `compose_apps`. |
| [`docs/disaster-recovery.md`](docs/disaster-recovery.md) | Stage 1 DR: SeaweedFS, `backup_agent`, GPG encryption. |
| [`docs/cloud-sync.md`](docs/cloud-sync.md) | Offsite replication to R2/B2/OCI: mechanism, retention, first-use setup. |
| [`docs/volume-maintenance.md`](docs/volume-maintenance.md) | Ad hoc in-place volume file removal/reset outside `cleanup.yaml`. |
| [`docs/secrets.md`](docs/secrets.md) | The `secrets` role, `bootstrap_secrets.py`, rotation. |

### Testing & CI

| Doc | Covers |
| :--- | :--- |
| [`docs/molecule-testing.md`](docs/molecule-testing.md) | Molecule scenario matrix and how to add one. |
| [`docs/molecule-fixtures.md`](docs/molecule-fixtures.md) | How fixtures avoid duplicating prod compose files, `app_registry` entries, and placeholder shapes. |
| [`docs/ci.md`](docs/ci.md) | The PR-checks pipeline: change-scoped jobs, boot-testing, deploy-ordering regression check. |

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

## Inventory

Two inventories exist for two different situations:

| Inventory | Used by | Host addressing | Purpose |
| :--- | :--- | :--- | :--- |
| `inventory/inventory.yaml` | `playbooks/deploy.yaml`, `playbooks/maintenance.yaml` | `<host>.{{ ddns_domain }}` (DNS name) | Day-to-day operation once DNS is up |
| `inventory/sos-inventory.yaml` | `playbooks/reset-network.yaml` | Static `192.168.20.x` IPs | Recovery path when DNS/network is down |

`inventory/inventory.yaml` also defines two groups the roles depend on directly:

- **`app_hosts`** — every host that owns `compose_apps` / `dns_zones` / `caddy_domain`; the `bind9` role iterates this group's `hostvars` to build DNS zone files.
- **`dns`** — the single host (`services`) the `bind9` role actually runs on.

## Ansible Playbooks

| Playbook File | Inventory | Description |
| :--- | :--- | :--- |
| `playbooks/deploy.yaml` | `inventory/inventory.yaml` | Master playbook — converges the entire infrastructure: Docker install, Caddy, BIND9, and every application. See [`docs/deployment-flow.md`](docs/deployment-flow.md). |
| `playbooks/cleanup.yaml` | `inventory/inventory.yaml` | Tears down stacks that are deployed/running on a host but no longer listed in its `compose_apps`, with a keep/delete policy for their on-disk content and named Docker volumes. See [`docs/cleanup.md`](docs/cleanup.md). |
| `playbooks/maintenance.yaml` | `inventory/inventory.yaml` | Server maintenance: `apt` upgrade + reboot-if-required, `fwupd` firmware updates + reboot-if-required. |
| `playbooks/reset-network.yaml` | `inventory/sos-inventory.yaml` | Re-applies `netplan` on every host; used when a host's network config needs a clean reset. |
| `playbooks/restore.yaml` | `inventory/inventory.yaml` | Restores one app's named volume(s) from a decrypted offsite backup archive (stage 1 DR). See [`docs/disaster-recovery.md`](docs/disaster-recovery.md). |
| `playbooks/volume-file-rm.yaml` | `inventory/inventory.yaml` | Removes specific, named file(s) from a volume that's staying deployed, without touching the rest of its content. See [`docs/volume-maintenance.md`](docs/volume-maintenance.md). |
| `playbooks/volume-reset.yaml` | `inventory/inventory.yaml` | Wipes a volume entirely and recreates it, restoring only Ansible-seeded content. See [`docs/volume-maintenance.md`](docs/volume-maintenance.md). |

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
- Filter roles by tags (e.g. skip the Docker Engine install on hosts that already have it):
  ```sh
  ansible-playbook playbooks/deploy.yaml --skip-tags "initial-setup"
  ```
- Pull/rebuild changed images and recreate their containers only:
  ```sh
  ansible-playbook playbooks/deploy.yaml --tags "images"
  ```
- Re-render Caddyfile/DNS zones, restarting only containers whose config
  changed:
  ```sh
  ansible-playbook playbooks/deploy.yaml --tags "infra"
  ```
  Both assume the host is already provisioned once (a full, untagged run
  first). See [Tags in `deployment-flow.md`](docs/deployment-flow.md#tags).
- Check target host variables (e.g. to confirm the resolved `compose_apps`/`app_registry` merge for a host):
  ```sh
  ansible-inventory -i inventory/inventory.yaml --host services
  ```

### `docker` commands

- Stop and remove all containers on a host:
  ```sh
  docker stop $(docker ps -q) && docker rm $(docker ps -aq)
  ```

## Applications

Everything routed through Caddy sits behind **Tinyauth** forward-auth by
default (per-route `auth: false` opts out, e.g. Cobalt, Dashy,
OpenSpeedTest), backed by **LLDAP** as the directory. **DIUN** watches
deployed images and notifies over Telegram on updates. **Beszel**
monitors host/container health lab-wide — see
[`docs/beszel.md`](docs/beszel.md). Every host runs a **`backup_agent`**
pushing GPG-encrypted archives to **SeaweedFS** on `storage` nightly —
see [`docs/disaster-recovery.md`](docs/disaster-recovery.md). The rest of
`docker/` is independently deployable Compose stacks (dashboards, media
tools, Minecraft, link shortener, pastebin, web terminal, etc.), each
just an `app_registry` entry plus a `docker/<app>/` directory. See
[`docs/adding-an-app.md`](docs/adding-an-app.md) to add one.

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

## Linting & Pre-commit

`.config/.pre-commit-config.yaml` wires up:

- `check-yaml`, `end-of-file-fixer`, `trailing-whitespace` — general hygiene
- [`gitleaks`](https://github.com/gitleaks/gitleaks) — secret scanning
- [`yamllint`](https://github.com/adrienverge/yamllint) — strict YAML style checks (`.config/.yamllint`)
- [`dclint`](https://github.com/docker-compose-linter/pre-commit-dclint) — lints/auto-fixes every `compose*.yaml`
- [`markdownlint-cli2`](https://github.com/DavidAnson/markdownlint-cli2) — lints every `*.md`

All of the above run at commit time. [`ansible-lint`](https://github.com/ansible/ansible-lint)
(lints `ansible/`; `docker/` excluded, it's Compose files not playbooks)
runs at **push** time instead — it always re-lints the whole `ansible/`
tree regardless of what changed, so it's too slow to pay on every commit.

All tool configs live under `.config/` (each hook is passed an explicit
`-c` flag, since these tools don't auto-discover configs there by
default). `ansible-lint` also gets `--project-dir ansible`, since it
resolves `roles_path` relative to cwd rather than the config file.

Run `pre-commit install` once after
cloning. CI enforces the same checks on every PR regardless of whether
hooks are installed locally — see [`docs/ci.md`](docs/ci.md).
