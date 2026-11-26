# Maintainer Workstation

The maintainer's laptop is the workstation: a WSL2 instance on Windows where the repo's checks run before a change is reviewed and pushed. What the laptop may hold, and what it may not, is decided in [ADR 0056 (Workstation credentials)](../../decisions/0056-credentials-held-by-the-maintainer-workstation/revision-000.md). The laptop is not provisioned or converged from this repository, so this page records what it needs and how to check that it works. The Python environment and the git hooks are set up as on the controller ([`controller-setup.md`](../deploy/controller-setup.md)), and only what differs is here.

## What it needs

- WSL2 with an Ubuntu distribution and systemd on (`systemd=true` under `[boot]` in `/etc/wsl.conf`), which Docker Engine's service needs.
- A memory cap for the WSL2 virtual machine, set in `.wslconfig` in the Windows user profile. A 16 GB laptop runs with half of it:

  ```ini
  [wsl2]
  memory=8GB
  swap=2GB

  [experimental]
  autoMemoryReclaim=gradual
  ```

  `wsl --shutdown` applies a change. A Molecule scenario that exhausts the cap is a reason to raise it or to run that scenario elsewhere, not to remove it.
- Docker Engine inside WSL2, installed from Docker's apt repository by the method in [Docker's install guide for Ubuntu](https://docs.docker.com/engine/install/ubuntu/), with the maintainer's account in the `docker` group. Docker Desktop is not used. The three `-docker` hooks and every Molecule scenario need a daemon. Membership of `docker` is root inside WSL2, which is no boundary from Windows, so WSL2 follows the same rules as the laptop.
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/), installed inside WSL2.
- [Google Chrome](https://www.google.com/chrome/), the Linux `.deb`, installed inside WSL2. The [doc site](../documentation/doc-site.md#building-the-site) draws its diagrams and checks its layout in it.
- A clone of the repository in the WSL2 home directory, not under `/mnt/c`.

To check the setup, in WSL2:

```bash
systemctl is-system-running; systemctl is-active docker
docker run --rm hello-world
free -h; uv --version; google-chrome --version
```

## Running the checks

From the clone, once `uv sync` has created the environment:

Every hook and the unit tests, from the repository root:

```bash
uv run pre-commit run --all-files
uv run pytest ansible/tests/ tools/tests/
```

One role's Molecule scenarios, from the repository root:

```bash
role=apt
cd "ansible/roles/$role" && uv run molecule test
```

The checks need no credential: CI runs the same ones on hosted runners with no secrets. The `generate-doc-indexes` hook writes the generated views, which git ignores and no commit holds ([`pre-commit.md`](pre-commit.md)).

## What it must not hold

The laptop holds the GitHub push credential, the coding-agent host key and a hardware-backed key to the operator host, and no other infrastructure credential: no shared SSH key, no OpenBao credential, no Tofu credential, no backup GPG key and no cached `main-domain`. Anything that needs one runs on the operator host.

Software that handles untrusted content with local tool access, such as a desktop assistant with file or tool access, does not run on the laptop, in Windows or in WSL2.
