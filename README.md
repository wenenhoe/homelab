# homelab
Homelab Configurations

## Setup

### Install required tools

- Install `uv`: [uv docs](https://docs.astral.sh/uv/getting-started/installation/)

- Install `pre-commit`:
```sh
uv tool install pre-commit --with pre-commit-uv
```

- Install `ansible`:
```sh
uv tool install ansible-core --with ansible
```

### Setup required tools

- Install pre-commit hooks: `pre-commit install`
