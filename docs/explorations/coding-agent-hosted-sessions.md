---
id: EXP-coding-agent-hosted-sessions
title: "Should coding-agent work run in a provider-hosted session or on an own host, and under what guards?"
type: exploration
status: open
summary: "Whether Claude Code cloud sessions take over from chat sessions for work on this repository, what keeps them in bounds, and what an own host remains for."
topic: security-hardening
related: [ADR-0050, ADR-0051, ADR-0055, ADR-0096, ADR-0112]
---

# Should coding-agent work run in a provider-hosted session or on an own host, and under what guards?

Changes are written today in chat sessions that cannot run containers, so Molecule scenarios and the Docker hooks reach their first run after delivery. A Claude Code cloud session runs them in a disposable virtual machine the provider operates. Whether it takes over this work, and what an own host is then for, depends on how far its workarounds hold and on a trial of real changes.

This covers work on this repository only.

## What bears on it

### What a hosted session does

- It starts from a fresh clone in a new virtual machine, reads the committed [`AGENTS.md`](../../AGENTS.md), and can deliver a series that replays as [`land_series`](../topics/engineering/landing-a-series.md) expects. Instructions kept outside the repository for chat sessions do not reach it.
- With the account's GitHub connection and without the Claude GitHub App on the repository, `git push` and creating a ref through the API are refused.
- Its own reminders and stop hooks can ask it to push, change the commit identity or add a session link. The [commit form](../topics/engineering/conventions.md#commits) and the delivery rules have to be what it follows.
- It can start subagents on its own. A repository's committed settings can deny or cap them in a session with one repository.
- It shares the account's usage limits with every other session, and the machine has 4 CPUs and about 16 GB of memory.
- Landing stays serial ([ADR 0112](../decisions/0112-landing-a-series-of-dependent-changes-on-main/revision-003.md)), so more sessions at once do not land work faster ([series landing throughput](series-landing-throughput.md)).

### What the environment needs

- **Network.** The default allowed list lacks `pkg-containers.githubusercontent.com`, where `ghcr.io` serves image layers, and `galaxy.ansible.com`. Both are added in the environment's settings, which are not part of the repository.
- **Docker** is installed and not running. Pulled images can be kept by the environment's cache; running processes are not. Anonymous Docker Hub pulls can be rate limited, and `mirror.gcr.io` can serve as a mirror for the session's own daemon.
- **Hooks.** `ansible-lint`, `dclint-docker`, `actionlint-docker`, `hadolint-docker` and the container hardening check pass. `hadolint-docker` runs an untagged image until [ADR 0096](../decisions/0096-knowing-the-pre-commit-hooks-that-run-are-the-reviewed-ones/revision-000.md)'s digest is in the config, and a cached copy can differ from the one CI pulls.

### What Molecule needs

Three changes to the session, none to the repository:

| Obstacle | Change | What it leaves different from CI |
| :--- | :--- | :--- |
| The machine uses cgroup v1, and the systemd in the Ubuntu 26.04 images starts only on cgroup v2 | `dockerd` starts in its own mount namespace with cgroup2 on `/sys/fs/cgroup`; the host's mounts stay | Only the `hugetlb` controller is offered, so containers get no memory or CPU limits |
| Outbound HTTPS from containers is signed by the environment's own certificate authorities | A `runc` wrapper adds those authorities to each container the session's daemon creates | Test containers trust more authorities. Containers started by a daemon inside a scenario are not given them by the wrapper |
| `*.localtest.me` does not resolve, and the proxy refuses it | Entries in `/etc/hosts`, and the domain in `NO_PROXY` | Nothing in the scenario itself |

With these, the `default` scenarios of `docker`, `compose`, `bind9` and `caddy` pass, and so does `secrets/vault_backed`. `host_hardening` passed with the cgroup2 `dockerd` alone, and `apt` with the machine's `dockerd` unchanged. The rest have not been run. The daemons inside a scenario pull from Docker Hub without a mirror.

None of the three is a documented feature of the environment, so an update to it can break any of them.

### Isolation and control

- The agent is root in the session's machine and creates privileged containers there. The boundary is the provider's virtual machine, one per session, and not an account inside it. That differs from what [ADR 0051](../decisions/0051-coding-agent-execution-isolation/revision-000.md) and the [runtime question](molecule-runtime-without-host-privilege.md) ask of an own host.
- The property of [ADR 0050](../decisions/0050-agent-authored-changes-reaching-production/revision-000.md) to keep is that the agent's environment cannot write to the GitHub remote. In a hosted session it rests on settings held by two providers, not on where a credential is stored.
- Connector traffic does not pass through the environment's allowed list.
- Prompts, files and command output are processed and stored by the provider, as in chat today. Price, limits and terms are the provider's to change.
- Running cloud sessions on one's own machines is offered to Team and Enterprise plans only. On a Pro or Max plan the fallback is Claude Code on an own host.

## Guards a hosted session would need

- The Claude GitHub App stays off the repository, which also leaves out auto-fix.
- GitHub is connected without sending the `gh` token (`/web-setup` sends it).
- No connectors, no scheduled or triggered sessions, and sessions kept private.
- The network stays on the default list plus the named domains.
- The refused writes are checked again after an update to the connection or the environment.
- One task to a session and one writer to a series. Subagents are denied at first, then allowed for reading only.
- What a session reports as verified is kept apart from what it assumed, and CI stays the authority.

## What the repository would need

- Committed Claude Code settings: no session link, `git push` denied, subagents denied or capped. A deny rule guides a session and is not a security boundary.
- The rules a hosted session needs, in the repository: never push, the delivery commands, and that the repository's rules win over a reminder or hook.
- A script that prepares Docker for a cloud session (the mirror, the cgroup2 namespace, the certificate wrapper and the host entries), run by a `SessionStart` hook that does nothing elsewhere. It is code that runs without being asked, so a change to it is reviewed like other tooling.
- A section in [`checks-without-docker.md`](../topics/engineering/checks-without-docker.md), or a topic doc beside it, for hosted sessions.

## Still to check

- Whether opening or merging a pull request, and other API writes, are refused too.
- Whether a `SessionStart` hook can start `dockerd` so that it stays running.
- The remaining scenarios, and how long the roles a change touches take.
- Whether a Mermaid diagram renders there; its image pulls.
- Whether a session given a real role change runs Molecule, reads a failure and fixes its cause without weakening the test.

## Options

- **Stay with chat sessions.** Nothing new to trust or maintain. Role changes keep arriving without having run.
- **Hosted sessions that deliver series, without the App.** Scenarios and Docker hooks run before delivery, and landing is unchanged. Costs the workarounds above, their upkeep, and reliance on one provider.
- **Hosted sessions with the App, opening pull requests.** Saves the download and replay. The agent's environment can then write to the repository, against ADR 0050's property, and the series flow's local review goes.
- **Claude Code on an own host** ([placement](coding-agent-host-placement.md)). Keeps the machine and its egress in the maintainer's hands, and should need none of the three Molecule changes on a cgroup v2 host. Costs the host, its upkeep and the stages that build it.

## Leaning

Hosted sessions without the App, trialled on a few projects or stages before anything depends on them, with an own host still pursued in case the provider's terms or plans change. What would change it: a GitHub write that cannot be refused, workarounds that break often, or a trial in which sessions still deliver changes that were never run.
