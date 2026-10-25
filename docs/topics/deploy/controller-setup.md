# Controller Setup

The one-time setup of the machine that runs `ansible-playbook` and the repo's Python tooling, the `controller` of the inventory. What each command does once it is set up is in [`ansible.md`](ansible.md), [`deployment-flow.md`](deployment-flow.md) and the docs linked below.

## What it needs

- [`uv`](https://docs.astral.sh/uv/getting-started/installation/), which manages the Python environment.
- Docker, running, for Molecule: each role's scenario spins up and tears down real containers.
- An SSH key at `~/.ssh/proxmox_vm_servers` with access to every target host. Both inventories name that path.
- A native `bao` CLI, for anything that talks to OpenBao from the controller. See [OpenBao CLI](#openbao-cli).
- The `tofu` CLI, only to work under `tofu/`. `required_version` in [`tofu/versions.tf`](../../../tofu/versions.tf) is the range the root module accepts, and the `tofu-checks` job in [`pr-checks.yml`](../../../.github/workflows/pr-checks.yml) pins the release CI runs.

## Python environment

Tooling is a `uv` project (`pyproject.toml` and `uv.lock`, which stay at the repo root). `ansible-core`, the `docker` Python SDK, `molecule`, `molecule-plugins` and `pre-commit` all live in one shared `.venv/`. `ansible-core` is used instead of the full `ansible` metapackage: the collections the repo needs are declared in [`ansible/requirements.yml`](../../../ansible/requirements.yml), at exact versions, for a reproducible dependency set.

```sh
uv sync                                                # creates .venv/ from pyproject.toml and uv.lock
source .venv/bin/activate                              # once per shell session
ansible-galaxy collection install -r ansible/requirements.yml
```

Instead of activating the environment, prefix any command with `uv run`, for example `uv run molecule test`.

## Git hooks

```sh
pre-commit install
```

This installs both the commit-time and push-time hooks. To run the same hooks on patches applied with `git am`, link the two `applypatch` hooks as well; the commands, and what runs when, are in [`pre-commit.md`](../engineering/pre-commit.md#applying-patches-with-git-am).

## OpenBao CLI

Install `bao` natively. It is a personal, one-time step and not Ansible-managed, since this machine's own OS can't be assumed the way a `managed_hosts` member's can. [`tools/openbao_utils/shell.py`](../../../tools/openbao_utils/shell.py) needs it.

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

The version and checksum are read out of the `openbao_cli` role's own defaults, the values that role installs on `security`, so there is no second, hand-copied pin to drift when the role's is bumped. The last four commands undo the standalone-server setup the `.deb`'s installer does unconditionally, which this machine has no use for; the role's `tasks/main.yaml` comment says why the removal runs on every install, not just the first.

## Before the first deploy

Fill in every value Ansible can't generate itself. The list, and how each is stored, is in [`secrets.md`](../secrets/secrets.md#bootstrapping-manual-secrets).

```sh
cd tools && python3 -m openbao_utils.bootstrap
```

It is safe to re-run: it only fills in what's missing.

## Where commands run from

Several tools resolve paths against the directory they start in.

| Command | Run from |
| :--- | :--- |
| `ansible`, `ansible-playbook` | `ansible/`, where `ansible.cfg` sets the inventory sources and `roles_path` |
| `python3 -m <package>` for a package under `tools/`, such as `openbao_utils.bootstrap` | `tools/` |
| `molecule` | the role's directory; see [`molecule-testing.md`](../engineering/molecule-testing.md) |
| `uv run pytest ansible/tests/ tools/tests/` | the repo root; see [`conventions.md`](../engineering/conventions.md) |
| `tofu` | `tofu/`, or `tofu -chdir=tofu` from the repo root |
