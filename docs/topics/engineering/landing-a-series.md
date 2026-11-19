# Landing a Patch Series

How a series of patches reaches `main` as pull requests with [`tools/land_series`](../../../tools/land_series), the maintainer-run tool [ADR 0112 (Landing a patch series)](../../decisions/0112-landing-a-series-of-dependent-changes-on-main/revision-001.md) describes. It replays the series, keeps each pull request as a local branch for review, then pushes, waits on and merges them one at a time under the maintainer's own `gh` login. A session that writes a series never holds a credential for it.

Run it from `tools/` in a clone of the repository, with `gh` logged in as a user who can bypass the `main-review` ruleset ([`branching.md`](branching.md#the-rulesets)):

```bash
cd tools
uv run python -m land_series SERIES.series --repo ..            # replay, check, keep branches
uv run python -m land_series SERIES.series --repo .. --land     # push, open, wait, confirm, merge
```

## The input

One plain-text `.series` file, or several: the tool takes more than one and reads them as one series.

- A **manifest**: one line per patch, `<id> <slug>`, then a blank line. The id is four digits and a letter (`0007a`).
- Optionally, in the manifest, a `# base: <branch>` comment line (`# base: develop`) naming the branch the series lands on, so the choice travels with the file. `--base` overrides it, files that name different bases are refused, and a series with neither lands on `main`. [`branching.md`](branching.md#choosing-the-branch-for-a-change) says which branch a change belongs on; the maintainer runs the command, so the choice stays theirs.
- Then the patches, a single mbox of `git format-patch` messages in the manifest's order. Write them as plain `git format-patch` output: ordinary `diff --git` headers, readable paths, and no encoded or binary bodies, so each patch can be read in full before it is replayed, which the stop list below relies on.

A number is a pull request and each letter is a commit in it. Commits that share a number share a slug, and a slug belongs to one number; the tool refuses anything else. Pull requests land in number order. A slug is lowercase kebab-case, and `main`, `maintenance` and `develop` are refused. A slug is not reused from an earlier series: it is the name of the pull request's branch. Keep a pull request to a few commits that each stand alone: a squash would lose each change's blame, and a long list is noise. The first commit's subject is the pull request's title.

A fix to a layer that has landed is a new commit with the next letter, or a new number. A file that repeats earlier layers unchanged is fine, since a commit already in the base is skipped, so a follow-up file can hold only the new commits.

## Replay

The replay applies the series on a scratch worktree of `origin/main` (fetched first; `--no-fetch` skips it), one `git am` per patch with the generated views reset between, and runs the checks that need no Docker after each commit ([`checks-without-docker.md`](checks-without-docker.md)). The project scope check runs with its base set to the state before the layer's pull request: the tip of the pull request before it in the run, or `origin/main` for the first one applied. A layer can therefore use a widening made by an earlier pull request of the same run, and fails if the widening is in its own pull request or missing, before a pull request exists. `--check COMMAND` can name that commit as `{pull_base}`. `--check COMMAND` adds a check. Before it applies anything the replay checks that the apply hooks are linked ([`pre-commit.md`](pre-commit.md#applying-patches-with-git-am)), that `pre-commit` is on `PATH` and that git has a committer identity, and stops naming what is missing.

- Once per pull request, after the checks of its last commit, the replay runs the Python unit tests (`pytest ansible/tests/ tools/tests/`, as CI's `python-unit-tests` job does) when CI would start that job: some file matching the `python_unit_tests` filter in `.github/detect-changes-filters.yml` changed for real between the pull request's base (the `{pull_base}` above) and its last commit, which [`ci.scope.filter_scope`](../../../tools/ci/scope/filter_scope.py) decides with the same no-op rule as `detect-changes`. A failure names the pull request's last commit and quotes the output; a pull request that does not need them says so in the progress lines. `--check COMMAND` replaces the default checks and these tests with it. A pre-push hook does not stand in for this: the tool's push runs hooks against the working tree and not the commit pushed, and the remote console pushes with hooks off.
- A commit already in the base, matched by author time and subject, is skipped. A pull request with only some of its commits in the base is refused.
- A layer that changes `.githooks/`, `.pre-commit-config.yaml`, `.config/`, a workflow, an action, `tools/` or the Python dependencies (`pyproject.toml`, `uv.lock`) stops for confirmation, since the replay and the checks run that code on this machine. The paths come from the commits `git am` makes with every hook off, which are then taken back out, not from the patch text, so no way of writing a patch hides one. With no terminal it stops and says why.
- `--dry-run` stops there and leaves nothing behind.

Otherwise the replay keeps each pull request as the local branch `series/<slug>`, the first on the base and each next on the last commit of the one before. Next to the git directory, in `land-series/<slug>.json`, it records the first and last commit and a hash of the patches the branch was built from. Review the branches as any other.

A branch kept by an earlier run is replaced when its record still matches; one that has changed, or that is checked out, makes the run stop before it changes anything. Switch to another branch first.

## Landing

`--land` replays nothing. Before it fetches or pushes anything it runs `gh auth status`, so a `gh` that is missing or logged out stops the run with that said, not at the first pull request. For each pull request in turn it:

1. Refuses a branch whose tip is not the recorded commit, one built from other patches than the file's, or one built on a tree other than the base's now. If the base moved only because the pull request before it just merged, the commits are moved onto its tip with the same trees, authors, dates and messages. Otherwise the message says whether the change still applies; run the replay again.
2. Pushes the branch (the branch name is the slug) and opens the pull request, or reuses one from that branch of this repository that is already at the same commit; a pull request from a fork's branch of the same name is ignored. The title is the first commit's subject; the body is the commit's body, or a list of the subjects for several.
3. Waits for every check the rulesets require on the base branch, read once with `gh api` before the first push. A required check that is not reported yet, such as `matrix-jobs-gate`, which only starts once the matrix jobs have finished, is waited for rather than counted as passed; a skipped one counts as passed; one that fails stops the run. After about 90 minutes it gives up and names what is still missing. This is CI and can take several minutes.
4. Prints the pull request's address and asks for confirmation. `--yes` confirms every merge in the run; with no terminal and no `--yes` it stops and leaves the pull request open, and running `--land` again picks up from it.
5. Merges it with `gh pr merge --admin --merge`, naming the pushed commit so a branch that moved after the checks is not merged, deletes the remote branch and the kept one, and fetches. A fetch that loses a race with another is retried; the merge is already recorded. If GitHub refuses the merge, the run stops with GitHub's reason (an unreported required check, say), the pull request is left open and listed as such, and running `--land` again continues from it.

Each pull request becomes a merge commit, so one reverts alone. A merge to `main` is a deploy ([`branching.md`](branching.md)).

`--base develop`, or `# base: develop` in the series file, lands on `origin/develop` instead of `origin/main`; the replay, the kept branches and the merges all use that base.

## Failures and the network

Every `git` and `gh` call goes through one runner (`tools/land_series/run.py`) that tells three failures apart: the program is not installed, it ran past its time limit (2 minutes for `gh`, 5 for the `git` calls that reach the remote) and was stopped, or it exited non-zero. Calls that only read (`pr list`, `api`, `ls-remote`) are tried up to three times, after 2 and then 4 seconds, when the failure is a timeout or reads like a dropped connection (a 502, 503 or 504, a reset, a DNS failure); the wait for checks treats a poll that failed that way as missed and takes the next one, and gives up after three in a row. A failure of any other kind is not repeated, and nothing that changes something (`push`, `pr create`, `pr edit`, `pr merge`) is ever repeated by the tool itself.

## Progress and results

Progress goes to stderr: what the tool is doing to which pull request, and the pull request's address once it exists. On a terminal, a live block under it shows the last lines the running check printed (the replay) or the required checks that have not passed yet (the wait for CI), and is erased when that step ends, so each leaves one line behind. A failed check prints its output in full as before. Nothing is drawn when stderr is not a terminal or `TERM` is `dumb`; a pipe or a log file gets the progress lines alone. The run ends with one line per pull request, `<number>  merged|left open  <url>`. A kept branch that is checked out cannot be deleted; the tool says so, and you switch away and run `git branch -D` yourself.

## Advice on a review

After the replay, and again before each merge prompt of `--land`, the tool applies the criteria of [`pr-review.md`](pr-review.md#when-it-is-worth-asking) to each pull request's own commits and prints `Worth asking for a review:` with the criteria that tripped, the files that tripped them and a pointer to how to ask. A pull request that trips none gets no line. It is advice: it changes no exit status and stops nothing, a diff it cannot read gives none, and `--yes` skips the merge prompt and so its advice too.

## Not for

- Changes to `tools/land_series` itself: apply those with `git am` ([`pre-commit.md`](pre-commit.md#applying-patches-with-git-am)), so the tool that lands a series is reviewed and merged before it is used on one.
- Changes to the rulesets or to who may bypass them.
