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
- Install pre-commit hooks: `pre-commit install`

## Interacting with `ansible`

- Test connectivity: `ansible all -m ping`
- Select hosts to run (Single/Multiple):
```sh
ansible-playbook deploy.yml --limit test
ansible-playbook deploy.yml --limit services,play
```
- Dry run: `ansible-playbook deploy.yml --check --diff`
