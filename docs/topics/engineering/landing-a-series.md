# Landing a Patch Series

How a series of patches reaches `main` as pull requests with [`tools/land_series`](../../../tools/land_series), the maintainer-run tool [ADR 0112 (Landing a patch series)](../../decisions/0112-landing-a-series-of-dependent-changes-on-main/revision-000.md) describes. It replays the series, keeps each pull request as a local branch for review, then pushes, waits on and merges them one at a time under the maintainer's own `gh` login. A session that writes a series never holds a credential for it.

Run it from `tools/` in a clone of the repository, with `gh` logged in as a user who can bypass the `main-review` ruleset ([`branching.md`](branching.md#the-rulesets)):

```bash
cd tools
uv run python -m land_series SERIES.series --repo ..            # replay, check, keep branches
uv run python -m land_series SERIES.series --repo .. --land     # push, open, wait, confirm, merge
```

## The input

One plain-text `.series` file, or several: the tool takes more than one and reads them as one series.

- A **manifest**: one line per patch, `<id> <slug>`, then a blank line. The id is four digits and a letter (`0007a`).
- Then the patches, a single mbox of `git format-patch` messages in the manifest's order.

A number is a pull request and each letter is a commit in it. Commits that share a number share a slug, and a slug belongs to one number; the tool refuses anything else. Pull requests land in number order. A slug is lowercase kebab-case, and `main`, `maintenance` and `develop` are refused. Keep a pull request to a few commits that each stand alone: a squash would lose each change's blame, and a long list is noise.

A fix to a layer that has landed is a new commit with the next letter, or a new number. A file that repeats earlier layers unchanged is fine, since a commit already in the base is skipped.

## Replay

The replay applies the series on a scratch worktree of `origin/main` (fetched first; `--no-fetch` skips it), one `git am` per patch with the generated views reset between, and runs the checks that need no Docker after each commit ([`checks-without-docker.md`](checks-without-docker.md)). The project scope check runs with its base set to `origin/main`, so a layer that needs a widened `allowed_paths` fails here, before a pull request exists. `--check COMMAND` adds a check.

- A commit already in the base, matched by author time and subject, is skipped. A pull request with only some of its commits in the base is refused.
- A layer that changes `.githooks/`, `.pre-commit-config.yaml`, a workflow, an action, `tools/` or the Python dependencies (`pyproject.toml`, `uv.lock`) stops for confirmation, since the replay and the checks run that code on this machine. With no terminal it stops and says why.
- `--dry-run` stops there and leaves nothing behind.

Otherwise the replay keeps each pull request as the local branch `series/<slug>`, the first on the base and each next on the last commit of the one before. Next to the git directory, in `land-series/<slug>.json`, it records the first and last commit and a hash of the patches the branch was built from. Review the branches as any other.

A branch kept by an earlier run is replaced when its record still matches; one that has changed, or that is checked out, makes the run stop before it changes anything. Switch to another branch first.

## Landing

`--land` replays nothing. For each pull request in turn it:

1. Refuses a branch whose tip is not the recorded commit, one built from other patches than the file's, or one built on a tree other than the base's now. If the base moved only because the pull request before it just merged, the commits are moved onto its tip with the same trees, authors, dates and messages. Otherwise the message says whether the change still applies; run the replay again.
2. Pushes the branch (the branch name is the slug) and opens the pull request, or reuses one already at the same commit. The title is the first commit's subject; the body is the commit's body, or a list of the subjects for several.
3. Waits for the required checks. This is CI and can take several minutes.
4. Prints the pull request's address and asks for confirmation. `--yes` confirms every merge in the run; with no terminal and no `--yes` it stops and leaves the pull request open, and running `--land` again picks up from it.
5. Merges it with `gh pr merge --admin --merge`, deletes the remote branch and the kept one, and fetches. A fetch that loses a race with another is retried; the merge is already recorded.

Each pull request becomes a merge commit, so one reverts alone. A merge to `main` is a deploy ([`branching.md`](branching.md)).

`--base develop` lands on `origin/develop` instead of `origin/main`; the replay, the kept branches and the merges all use that base.

## Progress and results

Progress goes to stderr: what the tool is doing to which pull request, and the pull request's address once it exists. The run ends with one line per pull request, `<number>  merged|left open  <url>`. A kept branch that is checked out cannot be deleted; the tool says so, and you switch away and run `git branch -D` yourself.

## Not for

- Changes to `tools/land_series` itself: apply those with `git am` ([`pre-commit.md`](pre-commit.md#applying-patches-with-git-am)), so the tool that lands a series is reviewed and merged before it is used on one.
- Changes to the rulesets or to who may bypass them.
