# My Homelab

[![Renovate enabled](https://img.shields.io/badge/renovate-enabled-brightgreen.svg)](https://renovatebot.com)
[![Trivy scheduled scan](https://github.com/wenenhoe/homelab/actions/workflows/trivy-scheduled.yml/badge.svg)](https://github.com/wenenhoe/homelab/actions/workflows/trivy-scheduled.yml)

A small fleet of Ubuntu hosts running Dockerized services, fully converged by Ansible — package installs, DNS zones, TLS routes, and every app's config are generated on every run. Apart from the few secrets that stay manual ([`secrets.md`](docs/topics/secrets/secrets.md#bootstrapping-manual-secrets)), there is no manual step on a target host beyond running `ansible-playbook`.

| Concern | Stack |
| :--- | :--- |
| Automation & networking | Ansible · Docker Compose · Caddy · BIND9 |
| Identity & secrets | OpenBao (Vault fork) · step-ca · LLDAP · Tinyauth |
| Data & ops | SeaweedFS · GitHub Actions · Molecule · Trivy · Renovate |

OpenTofu provisioning of the Proxmox VMs is partly built: [`tofu/`](tofu) holds the root module, its modules and their tests. [`vm-provisioning.md`](docs/topics/infra/vm-provisioning.md) says what exists and what doesn't, and [`project-planning.md`](docs/project-planning.md) lists what remains.

Reviewing this repo? [`reviewing-this-repo.md`](docs/topics/engineering/reviewing-this-repo.md) maps each claim it makes to the doc that explains it and the check that holds it up.

## Architecture

Four app hosts, `services`, `play`, `security` and `storage`, each run Docker Compose stacks behind their own Caddy instance, which terminates TLS for the host's own subdomain of `lan.{{ main_domain }}`. `tailscale` (a subnet router) and `cd-agent` (the pull-based CD jobs) sit outside the app group. Routes sit behind Tinyauth forward-auth with LLDAP as the directory unless a route opts out. Every image is pinned by digest and Renovate proposes each change as a pull request ([ADR 0083](docs/decisions/0083-making-a-deploy-run-the-images-its-commit-names/revision-000.md)). Each app host's named volumes are backed up nightly as encrypted archives to SeaweedFS on `storage` and relayed offsite ([`backup.md`](docs/topics/disaster-recovery/backup.md)), and nearly every secret is generated, cached and rotated through OpenBao on `security` ([`openbao.md`](docs/topics/secrets/openbao.md)).

[`system-overview.md`](docs/architecture/system-overview.md) shows which host runs what; the other diagrams under [`docs/architecture/`](docs/architecture/README.md) follow DNS, auth, secrets and backups.

## Hardware

Everything runs on one Proxmox host: 6-core i5-9400, 32GB RAM, an NVMe boot/VM disk (1TB) plus a secondary 1TB HDD for backups.

## Repository Layout

```
.
├── .config/                 # Tool configs (lint/format/pre-commit)
├── .githooks/               # Hooks that run the checks on patches applied with git am
├── .github/                 # CI workflows, PR-check scripts, Renovate config
├── ansible/                 # All automation: playbooks, inventory, roles
├── docker/                  # One directory per application
├── docs/                    # Topic docs, decisions, projects, diagrams
├── tofu/                    # OpenTofu root module: the Proxmox provider and the modules built on it
├── tools/                   # Python tooling, one package per domain
├── AGENTS.md                # Where an agent starts: the doc workflow's rules and stop conditions
├── SECURITY.md              # The security model and what it does not claim
└── pyproject.toml / uv.lock # uv project files (must stay at repo root)
```

Each app under `docker/<app>/` holds its `compose.yaml` (or `compose.yaml.j2` — see [`adding-an-app.md`](docs/topics/deploy/adding-an-app.md)) plus a `configs/` directory of Jinja2 templates that Ansible renders onto the target host — nothing is hand-authored on the servers themselves. `docker/molecule-dind/` is the one exception: it's Molecule test scaffolding, not a deployed app.

## Getting Started

```sh
uv sync
source .venv/bin/activate
ansible-galaxy collection install -r ansible/requirements.yml
pre-commit install
```

That sets up the Python environment, the Ansible collections and the git hooks. SSH access, the OpenBao CLI, `tofu`, the manual secrets and the directory each command runs from are in [`controller-setup.md`](docs/topics/deploy/controller-setup.md).

## Where to go next

| Theme | I want to… | Read |
| :--- | :--- | :--- |
| Operate | Set up the machine that runs Ansible | [`controller-setup.md`](docs/topics/deploy/controller-setup.md) |
| | Add an app | [`adding-an-app.md`](docs/topics/deploy/adding-an-app.md) |
| | Follow what a `deploy.yaml` run does | [`deployment-flow.md`](docs/topics/deploy/deployment-flow.md) |
| | Understand or restore a backup | [`backup.md`](docs/topics/disaster-recovery/backup.md) · [`restore.md`](docs/topics/disaster-recovery/restore.md) |
| | Work with secrets | [`secrets.md`](docs/topics/secrets/secrets.md) · [`secrets-rotation.md`](docs/topics/secrets/secrets-rotation.md) |
| Develop | Run or write tests | [`molecule-testing.md`](docs/topics/engineering/molecule-testing.md) · [`conventions.md`](docs/topics/engineering/conventions.md) |
| | Know what the pre-commit hooks check | [`pre-commit.md`](docs/topics/engineering/pre-commit.md) |
| | Understand CI | [`ci/pipeline.md`](docs/topics/engineering/ci/pipeline.md) |
| Understand | See the fleet on one page | [`system-overview.md`](docs/architecture/system-overview.md) |
| | Check a claim this repo makes against the check behind it | [`reviewing-this-repo.md`](docs/topics/engineering/reviewing-this-repo.md) |
| | See the security model and its limits | [`SECURITY.md`](SECURITY.md) |
| | Know why a design was chosen | [decisions](docs/decisions/README.md) |
| Contribute | See what is planned or in flight | [`project-planning.md`](docs/project-planning.md) · [projects](docs/projects/README.md) |
| | Work out where a new doc goes | [`docs/README.md`](docs/README.md) |
| | Start as an agent | [`AGENTS.md`](AGENTS.md) |
| Browse | Topic docs ([all](docs/topics/README.md)), by area | [deploy](docs/topics/README.md#deploy) · [infra](docs/topics/README.md#infra) · [services](docs/topics/README.md#services) · [secrets](docs/topics/README.md#secrets) · [disaster recovery](docs/topics/README.md#disaster-recovery) · [monitoring](docs/topics/README.md#monitoring) · [engineering](docs/topics/README.md#engineering) |
| | Decisions ([all](docs/decisions/README.md)), by area | [Deployment & platform](docs/decisions/README.md#deployment--platform) · [Ingress, TLS & PKI](docs/decisions/README.md#ingress-tls--pki) · [Secrets store](docs/decisions/README.md#secrets-store) · [Cloud credentials](docs/decisions/README.md#cloud-credentials) · [Backup & recovery](docs/decisions/README.md#backup--recovery) · [Monitoring & alerting](docs/decisions/README.md#monitoring--alerting) · [Repository & tooling](docs/decisions/README.md#repository--tooling) · [Security & hardening](docs/decisions/README.md#security--hardening) · [Documentation & process](docs/decisions/README.md#documentation--process) |

## License

Released under the [MIT License](LICENSE).
