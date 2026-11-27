# Working in a Claude Code Cloud Session

A [cloud session](https://code.claude.com/docs/en/claude-code-on-the-web) is a disposable virtual machine with a fresh clone of the repository, in which Docker runs. This page says what it needs, what the repository gives it and how it differs from CI, which stays the authority. A session delivers a change as every other one does ([`landing-a-series.md`](landing-a-series.md)).

## Settings outside the repository

These are set on the account and the [cloud environment](https://code.claude.com/docs/en/cloud-environments), and no file here can set them.

- **Network access** is Custom, keeping the default list, with `pkg-containers.githubusercontent.com` (where `ghcr.io` serves image layers) and `galaxy.ansible.com` added.
- **Setup script** and **environment variables** are empty.
- **GitHub** is connected without the Claude GitHub App on the repository, and not with `/web-setup`, which sends the local `gh` token.
- No connectors, no scheduled or triggered sessions, and one repository to a session: with several, the repository's settings and hooks are not read.

## What the repository sets

[`.claude/settings.json`](../../../.claude/settings.json) applies to Claude Code wherever it opens the repository, a clone on one's own machine included. A change to it is on [the stop list](landing-a-series.md#the-stop-list).

| Setting | Effect |
| :--- | :--- |
| `attribution.sessionUrl` is `false` | No session link in a commit or pull request, as [the commit form](conventions.md#commits) asks |
| `Agent` is denied | A session starts no subagents |
| `git push` and `gh` are denied | The commands a session would reach the remote with are refused |
| The `github` and `claude-code-remote` MCP servers are denied | Their tools, which write to GitHub or start and schedule sessions, are not offered; reading GitHub through them goes too |
| A `SessionStart` hook | Prepares Docker, in a cloud session only |

A deny rule matches the command as written, so it guides a session and is [not a security boundary](https://code.claude.com/docs/en/permissions): `git -C . push` is not matched. A server is denied by name, so one that is added or renamed is not covered.

## What the hook prepares

[`cloud_session.prepare`](../../../tools/cloud_session/prepare.py) runs when a session starts or resumes. The session's first reply waits for it, and its report is in the session's context. A step that fails is named there, and the session starts all the same. It changes the session's machine only.

- Where the machine uses cgroup v1, which the systemd in current Ubuntu images cannot start on, `dockerd` runs in its own mount namespace with cgroup2 on `/sys/fs/cgroup`. The machine's own mounts stay.
- Outbound HTTPS is signed by the environment's certificate authorities, so [`runc_ca.py`](../../../tools/cloud_session/runc_ca.py) is installed as dockerd's runtime and adds them to each container.
- The daemon pulls through `mirror.gcr.io`, unless the machine already has a `daemon.json`.
- The `localtest.me` names the Molecule scenarios use resolve to `127.0.0.1` and bypass the proxy.

`dockerd` logs to `/var/log/cloud-session-dockerd.log`. To run the preparation again, from the repository root, which leaves a running daemon alone:

```bash
(cd tools && python3 -m cloud_session.prepare)
```

Run this way it cannot set the proxy exceptions of later commands and says so.

## Running Molecule

The dependencies are not installed by the hook. In each new session, from the repository root:

```bash
uv sync --locked --group dev
```

```bash
(cd ansible && uv run ansible-galaxy collection install -r requirements.yml)
```

```bash
(cd ansible && uv run ansible-galaxy collection install -r roles/molecule_helpers/requirements.yml)
```

```bash
# paste alone; it waits for the role's name
read -r -p 'role: ' role
```

```bash
(cd "ansible/roles/$role" && uv run molecule test -s default)
```

[`molecule-testing.md`](../testing/molecule-testing.md) lists the scenarios.

## Where it differs from CI

- Only the `hugetlb` controller is offered under that cgroup2 mount, so containers get no memory or CPU limits.
- Test containers trust the environment's certificate authorities. Containers started by a daemon inside a scenario are not given them.
- The daemons inside a scenario pull from Docker Hub without the mirror.
- `hadolint-docker` runs an untagged image, and a cached copy can differ from the one CI pulls.

None of what the hook does is a documented feature of the environment, so an update to it can break any of it.
