# My Homelab
My Homelab using Ansible to deploy Docker containers

## Setup

- Install `uv`: [uv docs](https://docs.astral.sh/uv/getting-started/installation/)
- Install `pre-commit`:
```sh
uv tool install pre-commit --with pre-commit-uv
```
- Install `ansible`:
```sh
uv tool install ansible-core --with ansible
```
- Install pre-commit hooks:
```sh
pre-commit install
```

## Ansible Playbooks

| Playbook File | Inventory | Description |
| :--- | :--- | :--- |
| `deploy.yml` | `inventory.yaml` | The master playbook that imports other roles to configure the entire infrastructure. |
| `maintenance.yml` | `inventory.yaml` | Performs server maintenance activities such as package update. |
| `reset-network.yml` | `sos-inventory.yaml` | Resets network for entire infrastructure. |

## Basic commands

### `ansible` commands

- Test connectivity:
```sh
ansible all -m ping
```
- Select hosts to run (Single/Multiple):
```sh
ansible-playbook deploy.yaml --limit test
ansible-playbook deploy.yaml --limit test,prod
```
- Dry run:
```sh
ansible-playbook deploy.yaml --check --diff
```
- Filter roles by tags:
```sh
ansible-playbook deploy.yaml --skip-tags "initial-setup"
```
- Check target host variables:
```sh
ansible-inventory -i inventory.yaml --host experiment
```

### `docker` commands

- Stop and remove all containers:
```sh
docker stop $(docker ps -q) && docker rm $(docker ps -aq)
```
