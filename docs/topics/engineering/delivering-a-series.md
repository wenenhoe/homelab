# Delivering a Series

How a session turns the commits of a change into the `.series` file the maintainer lands ([`landing-a-series.md`](landing-a-series.md)), with [`tools/deliver_series`](../../../tools/deliver_series). [ADR 0123 (Preparing a series)](../../decisions/0123-preparing-a-series-for-delivery/revision-000.md) says why it is one command. It builds and checks the commits; [the replay](checks-without-docker.md#verifying-a-series-before-delivery) is still run by hand.

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

```bash
uv run python -m deliver_series "$plan" --repo ..
```

It prints the path of the series file. `--out DIR` names the directory it is written in, a new one otherwise; a directory inside the checkout is refused, since the file would be an untracked change. `--base BRANCH` is for a series that lands on a branch other than `main`, and puts `# base: BRANCH` in the manifest. The file is read back the way `land_series` reads it before it is written.

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

What it checks of a commit: author and committer are the maintainer, who is the newest author on the base that is not a bot; both dates are at `+0800`; the subject is a Conventional Commits subject of at most 72 characters, lowercase after the colon, with no id, number or slug in it; the last paragraph holds exactly one `Co-Authored-By: <model name> <noreply@anthropic.com>` trailer and no trailer but `Plan-Confirmed:` or `Editorial-Fix:`; and no session link is in the message.
