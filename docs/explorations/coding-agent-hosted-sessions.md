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
- With the account's GitHub connection and without the Claude GitHub App on the repository, reads work and writes are refused with a 403. Tried on a scratch repository connected that way, through the session's GitHub tools and through REST requests: creating a branch, opening a pull request, commenting on one, creating an issue, committing a file to `main` and merging an open pull request. `git push` was refused too.
- Its own reminders and stop hooks can ask it to push, change the commit identity or add a session link. The [commit form](../topics/engineering/conventions.md#commits) and the delivery rules have to be what it follows.
- A session given only a project's name built its first stage, added a Molecule scenario, read the scenario's failure and fixed its cause. Its clone was one merge behind `main`, so it built to wording the project doc no longer had, and nothing in the session noticed. It did not try the replay, and it attached the series file only when asked.
- Given the same kind of prompt again, with the rules to fetch first, replay and attach in `AGENTS.md`, a session built from the current `main`, showed with a control that its new Molecule scenario can fail, replayed its series on a fresh clone and attached it unasked. It declined a stop hook that asked it to push and to change the commit identity. The scope did not list a file the new scenario needs: it stopped to ask, with options that included folding the scenario into `default`, and on approval delivered the widening as an earlier layer of the series.
- A review of that delivery found what its checks had passed: a tag selection under which the change had no effect, a form of input the parser silently ignored, and a report of only the new scenario where the project requires every scenario of the role. Asked, it fixed them and ran the rest. The tag fix the review proposed then stopped a task from running under `--skip-tags`, which the session's new test, the replay and the scenarios did not show either.
- The pull request for that stage then failed the [Molecule coverage floor](../topics/engineering/ci/gates.md#molecule-coverage-gate): a new task loops over mounted directories, and no scenario mounted one. Neither the session, which ran every scenario of the role, nor the replay, nor the review had run the coverage report. Neither `AGENTS.md` nor the [checks that need no Docker](../topics/engineering/checks-without-docker.md) names the floor.
- It can start subagents on its own. A repository's committed settings can deny or cap them in a session with one repository.
- It shares the account's usage limits with every other session, and the machine has 4 CPUs and about 16 GB of memory.
- Landing stays serial ([ADR 0112](../decisions/0112-landing-a-series-of-dependent-changes-on-main/revision-004.md)), so more sessions at once do not land work faster ([series landing throughput](series-landing-throughput.md)).

### What the environment needs

- **Network.** The default allowed list lacks `pkg-containers.githubusercontent.com`, where `ghcr.io` serves image layers, and `galaxy.ansible.com`. Both are added in the environment's settings, which are not part of the repository.
- **Docker** is installed and not running. Pulled images can be kept by the environment's cache; running processes are not. Anonymous Docker Hub pulls can be rate limited, and `mirror.gcr.io` can serve as a mirror for the session's own daemon.
- **Hooks.** `ansible-lint`, `dclint-docker`, `actionlint-docker`, `hadolint-docker` and the container hardening check pass. `hadolint-docker` runs an untagged image until [ADR 0096](../decisions/0096-knowing-the-pre-commit-hooks-that-run-are-the-reviewed-ones/revision-000.md)'s digest is in the config, and a cached copy can differ from the one CI pulls.

### What Molecule needs

Three changes to the session, made by the [preparation hook](../topics/engineering/hosted-sessions.md#what-the-hook-prepares):

| Obstacle | Change | What it leaves different from CI |
| :--- | :--- | :--- |
| The machine uses cgroup v1, and the systemd in the Ubuntu 26.04 images starts only on cgroup v2 | `dockerd` starts in its own mount namespace with cgroup2 on `/sys/fs/cgroup`; the host's mounts stay | Only the `hugetlb` controller is offered, so containers get no memory or CPU limits |
| Outbound HTTPS from containers is signed by the environment's own certificate authorities | A `runc` wrapper adds those authorities to each container the session's daemon creates | Test containers trust more authorities. Containers started by a daemon inside a scenario are not given them by the wrapper |
| `*.localtest.me` does not resolve, and the proxy refuses it | Entries in `/etc/hosts`, and the domain in `NO_PROXY` | Nothing in the scenario itself |

With these, every scenario of `compose`, `bind9`, `caddy` and `compose_app` passes, and so do `docker`'s `default` and `secrets/vault_backed`. `host_hardening` passed with the cgroup2 `dockerd` alone, and `apt` with the machine's `dockerd` unchanged. The rest have not been run. In a later session the hook made all three changes, `dockerd` stayed running, and `docker`'s `default` and `secrets/vault_backed` passed with the registry mirror configured, each in about two and a half minutes and with no pull refused. The daemons inside a scenario pull from Docker Hub without a mirror.

None of the three is a documented feature of the environment, so an update to it can break any of them.

### How long it takes, and what the docs leave open

- A scenario of those four roles took from under a minute to about six, and seven `compose` scenarios, the new one included, about 16 minutes together. The Python unit tests took 7 and a half minutes, and a replay of three commits a little over 3.
- A round of building and fixing took about an hour. The session ran scenarios one at a time, as [`molecule-test-all.sh`](../../ansible/scripts/molecule-test-all.sh) does, though the machine has 4 CPUs and CI splits them across runners. The documented command for the unit tests names no `-n`, while CI and the replay run them over all cores.
- Installing the Galaxy collections outlasted a two-minute foreground limit and finished in the background.
- The second delivery's replay ran every commit-stage hook except `zizmor`, which the session skipped from the start. `ansible-lint`, run at the pre-push stage, had real findings. `dclint` passed a first full run and failed the replay of the same files, for a reason not found.
- The session reported three gaps. Setting a project `building` [asks for](../projects/README.md) a changed stage table or a `Plan-Confirmed:` trailer, while the [commit form](../topics/engineering/conventions.md#commits) allows no trailer of that kind. Nothing in the [cloud session doc](../topics/engineering/hosted-sessions.md) says that the pre-push check of a series that widens a scope is run layer by layer. Its own instructions asked it to push to a branch, against `AGENTS.md`.

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

## What the repository holds

Committed Claude Code settings, the [rules for a coding agent](../../AGENTS.md#rules-for-a-coding-agent), the preparation hook and [its topic doc](../topics/engineering/hosted-sessions.md). A deny rule in those settings guides a session and is not a security boundary.

## Still to check

- The scenarios of the other roles.
- Whether a Mermaid diagram renders there; its image pulls.
- Whether scenarios run side by side on one daemon, how many the machine holds, and what that saves.
- Whether a session runs the coverage report before it delivers, once the rules it reads name the floor.
- How much a review still changes in a delivery, over more than one stage and project.

## Options

- **Stay with chat sessions.** Nothing new to trust or maintain. Role changes keep arriving without having run.
- **Hosted sessions that deliver series, without the App.** Scenarios and Docker hooks run before delivery, and landing is unchanged. Costs the workarounds above, their upkeep, and reliance on one provider.
- **Hosted sessions with the App, opening pull requests.** Saves the download and replay. The agent's environment can then write to the repository, against ADR 0050's property, and the series flow's local review goes.
- **Claude Code on an own host** ([placement](coding-agent-host-placement.md)). Keeps the machine and its egress in the maintainer's hands, and should need none of the three Molecule changes on a cgroup v2 host. Costs the host, its upkeep and the stages that build it.

## Leaning

Hosted sessions without the App, trialled on a few projects or stages before anything depends on them, with an own host still pursued in case the provider's terms or plans change. What would change it: a GitHub write that cannot be refused, workarounds that break often, or a trial in which sessions still deliver changes that were never run.
