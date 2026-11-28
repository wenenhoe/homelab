# Delivering a Series

How a session turns the commits of a change into the `.series` file the maintainer lands ([`landing-a-series.md`](landing-a-series.md)), with [`tools/deliver_series`](../../../tools/deliver_series). [ADR 0123 (Preparing a series)](../../decisions/0123-preparing-a-series-for-delivery/revision-000.md) says why it is one command. It checks the commits, builds the series file, replays it, runs the push stage and prints the handover, so no step of delivery is carried out by hand. What is particular to this repository (its remote, the committer, the hooks and their needs, the tooling paths and the maintainer's commands) is one object, [`repository.py`](../../../tools/deliver_series/repository.py).

It runs only where `CLAUDE_CODE_REMOTE` is `true` and refuses anywhere else, since a series is written on a machine that is thrown away ([`hosted-sessions.md`](hosted-sessions.md)). A cut of the commits into layers comes first: [`landing-a-series.md`](landing-a-series.md#cutting-a-series) says what is a commit and what is a layer.

## The plan

One line per layer, in landing order, in a file written outside the checkout:

```text
<slug> <number of commits> [<title>]
```

- The commits are those above `origin/<base>`, oldest first, and the counts add up to all of them.
- A layer of one commit may leave out its title, which is then its commit's subject. A layer of several is given one, a subject of [the commit form](conventions.md#commits) of at most 72 characters ([naming a layer](landing-a-series.md#naming-a-layer)).
- Numbering starts at `0001`, or after the highest number in each series file given with `--after`, the files not yet merged. A slug of those files is not reused.

For example, a layer of two commits and one of a single commit:

```text
gateway-vm 2 feat(gateway): declare the production gateway
gateway-docs 1
```

## Running it

From `tools/` in the checkout, with the branch on the tip of the base:

```bash
# paste alone; it waits for the plan file's path
read -r -p 'plan file: ' plan
```

A replay can run longer than the 10 minutes a foreground command is given, so run it in the background, with what it prints in a log file. Pass `--patches-read` only after reading the patches of the commits on the stop list:

```bash
out=$(mktemp -d)
log="$out.log"
(uv run python -m deliver_series "$plan" --repo .. --out "$out" --patches-read; echo "exit $?") > "$log" 2>&1 &
run=$!
```

Then wait for the process rather than for a length of time. This returns when the run ends, or after 590 seconds, in which case run it again:

```bash
timeout 590 tail --pid="$run" -f "$log"
```

The options:

| Option | Meaning |
| :--- | :--- |
| `--patches-read` | The patches of the commits on [the stop list](landing-a-series.md#the-stop-list) were read, so they may be replayed. Without it a series with such a commit is refused, naming the commits and their files |
| `--build-only` | Write the series file and stop: nothing is replayed, no hook is skipped and no handover is printed |
| `--out DIR` | The directory for the series file and its log, a new one otherwise. One inside the checkout is refused, since the file would be an untracked change |
| `--base BRANCH` | The branch the series lands on, `main` otherwise; it puts `# base: BRANCH` in the manifest |
| `--after FILE` | A series file not merged yet, which numbering follows (repeatable) |

## What it does

1. Refuses where `CLAUDE_CODE_REMOTE` is not `true`, then fetches the base and checks the checkout and each commit ([what it refuses](#what-it-refuses)).
2. Probes the machine and decides [which hooks to skip](#what-it-skips). It installs nothing.
3. Writes the series file as `.series.unchecked` and reads it back the way `land_series` does.
4. Clones the remote fresh, with its history, and installs the hooks there. A base that moved since the series was built is refused.
5. Replays the series with `land_series --dry-run --accept-stops` on that clone, as [the replay](landing-a-series.md#replay) describes, with the `SKIP` it decided. `land_series` is run as it is in the checkout, unchanged. Its output is `<first number>-<last number>.log` beside the series file, and its first progress line names it.
6. Applies the series to the clone and, for each pull request in turn, runs the pre-push hooks on its last commit over its own commits, as `--land` does.
7. Renames the file to `.series` only when both passed, and prints the handover.

A failure of the replay or the push stage names the failing commit and quotes the last lines of the output, leaves no `.series` file, and exits non-zero.

## What it refuses

It fetches the base first and writes nothing in any of these cases:

| Refused | Why |
| :--- | :--- |
| `CLAUDE_CODE_REMOTE` is not `true` | It is not a session on a disposable machine |
| The working tree has a staged, unstaged or untracked change | The series holds commits only, so the change would be left out |
| The branch is not on the tip of `origin/<base>` | The series would be replayed and landed on a different base |
| A merge among the commits, or a plan that does not count every commit | A series is a line of commits, each in a layer |
| A commit without [the commit form](conventions.md#commits) | Every such commit is named with what is wrong, at once |
| A binary or encoded patch | `land_series` reads each patch in full before it replays it |
| A commit on the stop list, without `--patches-read` | Its patch has to be read first |

What it checks of a commit: the author is the maintainer, who is the newest author on the base that is not a bot, and the committer is `Claude <noreply@anthropic.com>`; both dates are at `+0800`; the subject is a Conventional Commits subject of at most 72 characters, lowercase after the colon, with no id, number or slug in it; the last paragraph holds exactly one `Co-Authored-By: <model name> <noreply@anthropic.com>` trailer and no trailer but `Plan-Confirmed:` or `Editorial-Fix:`; and no session link is in the message.

## What it skips

A hook is skipped only when the probe of what it needs finds that missing, and the skip is named with the reason in the progress lines and in the handover. A hook whose need is met runs, and a failure of it fails the delivery. A `SKIP` already in the environment is ignored.

| Need | Probe | Hooks skipped without it |
| :--- | :--- | :--- |
| A Docker daemon | `docker info` succeeds | `dclint-docker`, `hadolint-docker`, `actionlint-docker` |
| A download of the Go toolchain | `proxy.golang.org` serves the toolchain list | `gitleaks` |
| The GitHub API | The request `zizmor`'s `ref-confusion` audit makes, the branches of `actions/checkout`, is answered 200 | `zizmor` |
| The Ansible collections | Each collection `ansible/requirements.yml` names, but not one pinned by a git URL, is in `ansible-galaxy collection list` | `ansible-lint`, which runs only in the push stage |

In a [cloud session](hosted-sessions.md), once its hook has started `dockerd`, `gitleaks` and the three Docker hooks run. `zizmor` is skipped there, the request of its audit being refused with a 403. `ansible-lint` runs only after [the collections are installed](hosted-sessions.md#running-molecule). A run of a series of two commits took about four minutes with Docker and about three without it.

A test fails when the pre-commit configuration holds a hook ending in `-docker` that is not listed, or a listed hook that the configuration does not have. The collections are present in a [cloud session](hosted-sessions.md) only once [installed](hosted-sessions.md#running-molecule).

## The handover

It prints the series file's path, the layers, the commits on the stop list with their files, the layers that touch a hook, CI or tooling path, and what was not checked: each skipped hook with its reason, and each changed Ansible role, since no Molecule scenario is run. It ends with the maintainer's replay and `--land` commands, which a test holds equal to those of [`landing-a-series.md`](landing-a-series.md#replay). Reply with it and attach the series file.
