# Landing a Patch Series

How a series of patches reaches `main` as pull requests with [`tools/land_series`](../../../tools/land_series), the maintainer-run tool [ADR 0112 (Landing a patch series)](../../decisions/0112-landing-a-series-of-dependent-changes-on-main/revision-002.md) describes. It replays the series, keeps each pull request as a local branch for review, then pushes, waits on and merges them one at a time under the maintainer's own `gh` login. A session that writes a series never holds a credential for it.

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
- Optionally, in the manifest, a `# title <number>: <subject>` comment line (`# title 0004: feat(tofu): declare the production gateway`) naming the title of the pull request with that number, as [ADR 0118 (Layer pull request title)](../../decisions/0118-the-title-of-a-layers-pull-request/revision-000.md) decides. The title is a subject of the usual form ([`conventions.md`](conventions.md#commits)), so it is refused when it is longer than 72 characters or is not one, when the manifest lists no such number, and when a number is given two titles, in one file or in two. A layer with no title line is titled by its first commit's subject.
- Then the patches, a single mbox of `git format-patch` messages in the manifest's order. Write them as plain `git format-patch` output: ordinary `diff --git` headers, readable paths, and no encoded or binary bodies, so each patch can be read in full before it is replayed, which the stop list below relies on.

A number is a pull request and each letter is a commit in it. Commits that share a number share a slug, and a slug belongs to one number; the tool refuses anything else. Pull requests land in number order. A slug is lowercase kebab-case, and `main`, `maintenance` and `develop` are refused. A slug is not reused from an earlier series: it is the name of the pull request's branch. Keep a pull request to a few commits that each stand alone: a squash would lose each change's blame, and a long list is noise. [Cutting a series](#cutting-a-series) says what is a commit and what is a layer, and [Naming a layer](#naming-a-layer) its slug and its title.

A fix to a layer that has landed is a new commit with the next letter, or a new number. A file that repeats earlier layers unchanged is fine, since a commit already in the base is skipped, so a follow-up file can hold only the new commits.

## Cutting a series

A layer costs and a commit does not. Each layer is a full CI run waited for before the next one opens, a merge to `main` ([a deploy](branching.md)), a confirmation by hand, and the unit one revert undoes. A commit costs none of that and keeps its own blame. A series is therefore a few layers of several commits each, never a layer per commit.

**A commit** is one logical change that stands alone. The replay checks every commit, so one that cannot pass without the next is not yet a commit. A change's tests and the docs that describe it ride with it, and a correction found while writing the series is made in the commit it corrects: a series adds no fix-up of its own, unlanded work.

**A layer** starts as the whole of one theme: everything in the series that serves one purpose, such as one feature, one fix, or one decision and the docs it moves. A second layer needs a reason from this list, and no other counts:

1. **A stage.** A project stage is one pull request ([What a stage is](../../projects/README.md#what-a-stage-is)).
2. **An order the checks force.** The replay judges a layer's project scope against the state before its pull request, so a widened `allowed_paths` has to merge in an earlier layer than the one that needs it. One early layer carries every widening the series needs, not one layer per widening.
3. **A revert of its own.** The rest of the series still makes sense without it, and the maintainer could want to undo one and keep the other. If both would always be undone together, they are one layer.
4. **The stop list or a review.** A layer that changes a path on [the stop list](#replay), or that trips a criterion of [`pr-review.md`](pr-review.md#when-it-is-worth-asking), stays apart from layers that do not, so the confirmation and the review attach to the code that asked for them. The docs that describe that code stay with it.

These always join the layer that does the work, as commits in it:

- Opening a stage, marking it done, and any other edit to the project doc's table or status.
- Edits to one document, or to one project, decision or exploration: one layer, with a commit for each point that stands alone.
- A layer of fewer than about 30 changed lines that shares a file or a theme with a neighbouring layer.

A docs-only layer has a reason of its own only under the first two; otherwise it joins the nearest docs layer of the series, whatever the theme.

Before writing the manifest, list the layers and say under which of the four reasons each is separate from the one before. A layer with none becomes commits in that one. A layer past about six commits is checked the same way for a split.

## Naming a layer

A layer is known by two names: its slug, which is the branch and shows in the merge commit, and its title, which is a subject ([`conventions.md`](conventions.md#commits) has its form).

- **The slug names the theme.** Two to four words, about 30 characters at most. It leaves out what the title carries, the type (`feat-`, `docs-`) and the kind of file (`-exploration`), and it names the theme rather than the step (`gateway-vm-startup-order`, not `stage-four-done`). Layers of one series that carry on one piece of work begin with the same word, so their branches sort together.
- **The title names the layer.** It is the one line `main`'s history keeps for the change, so it says what the whole layer is for. A layer of one commit is titled by that commit's subject. A layer of several is given a `# title` line ([the input](#the-input)), because its first commit is in dependency order and usually names one step, such as a refactor; the line is left out only when the first commit already names the layer.

## Replay

The replay applies the series on a scratch worktree of `origin/main` (fetched first; `--no-fetch` skips it), one `git am` per commit with every hook off, so a patch is applied as written, and runs the checks that need no Docker after each commit ([`checks-without-docker.md`](checks-without-docker.md)). The project scope check runs with its base set to the state before the layer's pull request: the tip of the pull request before it in the run, or `origin/main` for the first one applied. A layer can therefore use a widening made by an earlier pull request of the same run, and fails if the widening is in its own pull request or missing, before a pull request exists. `--check COMMAND` can name that commit as `{pull_base}`. `--check COMMAND` adds a check. Before it applies anything the replay checks that git has a committer identity, and stops naming what is missing. The generated views are not committed, so a patch holds none of them, a series that edits what a view is written from applies like any other, and two series that each add a decision or a project do not conflict on a view.

- Once per pull request, after the checks of its last commit, the replay runs the Python unit tests (`pytest ansible/tests/ tools/tests/`, as CI's `python-unit-tests` job does) when CI would start that job: some file matching the `python_unit_tests` filter in `.github/detect-changes-filters.yml` changed for real between the pull request's base (the `{pull_base}` above) and its last commit, which [`ci.scope.filter_scope`](../../../tools/ci/scope/filter_scope.py) decides with the same no-op rule as `detect-changes`. A failure names the pull request's last commit and quotes the output; a pull request that does not need them says so in the progress lines. `--check COMMAND` replaces the default checks and these tests with it. The replay is the commit stage: what committing each patch with the hooks installed would run, and `pre-commit run --all-files` is how the `pre-commit`-stage hooks run here, since `git am` runs no hook. The pre-push hooks belong to [the push](#landing), not to the replay.
- A commit already in the base, matched by author time and subject, is skipped. A pull request with only some of its commits in the base is refused.
- A layer that changes `.githooks/`, `.pre-commit-config.yaml`, `.config/`, a workflow, an action, `tools/` or the Python dependencies (`pyproject.toml`, `uv.lock`) stops for confirmation, since the replay and the checks run that code on this machine. The paths come from the commit `git am` makes, with every hook off, not from the patch text, so no way of writing a patch hides one, and the layer is applied before it is asked about since applying runs nothing it adds. With no terminal it stops and says why.
- `--dry-run` stops there and leaves nothing behind.

Otherwise the replay keeps each pull request as the local branch `series/<slug>`, the first on the base and each next on the last commit of the one before. Next to the git directory, in `land-series/<slug>.json`, it records the first and last commit and a hash of the patches the branch was built from. Review the branches as any other.

A branch kept by an earlier run is replaced when its record still matches; one that has changed, or that is checked out, makes the run stop before it changes anything. Switch to another branch first.

## Landing

`--land` replays nothing. Before it fetches or pushes anything it runs `gh auth status`, so a `gh` that is missing or logged out stops the run with that said, not at the first pull request. For each pull request in turn it:

1. Refuses a branch whose tip is not the recorded commit, one built from other patches than the file's, or one built on a tree other than the base's now. If the base moved only because the pull request before it just merged, the commits are moved onto its tip with the same trees, authors, dates and messages. Otherwise the message says whether the change still applies; run the replay again.
2. Runs the pre-push hooks, then pushes the branch (the branch name is the slug) and opens the pull request, or reuses one from that branch of this repository that is already at the same commit; a pull request from a fork's branch of the same name is ignored. The title is the one the manifest names, or else the first commit's subject; the body is the commit's body, or a list of the subjects for several. A pull request that is already open and has another title than the file's is given the file's, whether or not its branch changed.
3. Waits for every check the rulesets require on the base branch, read once with `gh api` before the first push. A required check that is not reported yet, such as `matrix-jobs-gate`, which only starts once the matrix jobs have finished, is waited for rather than counted as passed; a skipped one counts as passed; one that fails stops the run. After about 90 minutes it gives up and names what is still missing. This is CI and can take several minutes.
4. Prints the pull request's address and asks for confirmation. `--yes` confirms every merge in the run; with no terminal and no `--yes` it stops and leaves the pull request open, and running `--land` again picks up from it.
5. Merges it with `gh pr merge --admin --merge`, naming the pushed commit so a branch that moved after the checks is not merged, deletes the remote branch and the kept one, and fetches. A fetch that loses a race with another is retried; the merge is already recorded. If GitHub refuses the merge, the run stops with GitHub's reason (an unreported required check, say), the pull request is left open and listed as such, and running `--land` again continues from it.

The pre-push hooks are what `git push` would run: `pre-commit run --hook-stage pre-push --from-ref <the commit before the pull request> --to-ref HEAD`, in a scratch worktree of the commit about to be pushed, so they test that commit and not this clone's working tree. The base is the branch's tip as just fetched, which holds the pull requests before it. They run once per push, so not for a branch already at the kept commit, and whether or not the `pre-push` git hook is installed; `SKIP` skips hooks as it does in the replay. The push itself then runs with every hook off, so none runs twice. A hook that fails stops the run before that pull request is pushed, and the pull requests before it stay merged, as a failed push would leave them; fix the cause and run `--land` again, or rebuild the branches with a replay if the fix changes the series. `ansible-lint` is one of them, and runs only when the pull request touches what its `files` pattern matches.

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
