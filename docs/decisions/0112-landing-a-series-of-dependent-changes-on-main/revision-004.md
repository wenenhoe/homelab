---
id: ADR-0112
revision: 4
type: adr
title: Landing a series of dependent changes on main
short: Landing a patch series
solution: A maintainer-run tool lands a series one pull request at a time, replaying it first, asking once about the code that can run on that machine and merging each layer with the admin bypass
summary: How a series of patches reaches main as pull requests when main refuses any update outside a merged pull request and a pull request based on another branch sees neither main's project docs nor a stable head.
topic: repository-tooling
status: accepted
supersedes: 3
related: [ADR-0076]
---

# 0112. Landing a series, asking once about code that can run in the clone

## Problem

Work is written as a series of patches, and a project's stages are each meant to be one pull request, so a series is the normal shape of a change. Landing one by hand is slow. What has to be true: each layer reaches `main` as its own pull request with a merge commit, so one layer can be reverted alone; every check runs on a layer against the state `main` will be in; a failure that only the order of layers causes shows before a pull request exists; and no credential other than the maintainer's own can merge to `main`.

## Context

- `main` accepts a change only through a pull request merged with the Admin bypass, and the `main-review` ruleset's `update` rule refuses every other actor ([`branching.md`](../../topics/engineering/branching.md#the-rulesets), [ADR 0076 (Branch separation)](../0076-keeping-what-production-runs-apart-from-work-in-progress/revision-000.md)). GitHub's stacked pull requests merge a whole stack as one update, which that rule refuses. Merging one pull request at a time with the bypass works. `gh pr merge --admin --merge` merges a pull request into `main` through that bypass from the command line, and `main` has no "require branches to be up to date" rule.
- A stacked layer is based on the branch below it. The `pull_request` branch filter lists no `stack/**`, so an upper layer gets no run and its required checks never report, and GitHub rebases the remaining layers after each merge, each with a new head SHA and a full run: N(N-1)/2 extra runs for N layers.
- The project scope check judges a pull request against the project docs as they stood on its base, so a layer that needs a widened `allowed_paths` fails until the widening has merged. CI's base for a layer landed after the one before it has that layer's tip tree, because the tool pushes a layer only once the one before it has merged. A check built on `origin/main` for every layer of a run therefore judges the changes of all the layers up to it, which CI never does.
- The generated views are not committed ([ADR 0117 (Generated doc views)](../0117-delivering-the-generated-doc-views-to-readers/revision-000.md)), so a series holds no view, `git am` has no hook that regenerates one, and two series that each add a decision or a project do not conflict on a view.
- Series are rare, and most projects' stages are chains. Layers that share no file can still depend on each other, and layers that each flip a row in one project doc conflict when applied independently.

**Threat model.** The asset is `main`, which the CD agent deploys. A tool that applies a series replays patches and runs the checks on the maintainer's machine, so a patch that changes the code the replay runs would execute before CI sees it. A coding agent's committed settings under `.claude/` name commands it runs when a session is opened in a checkout, a kept branch included, before the pull request merges. A hook installed in the maintainer's clone runs code from that clone's working tree, which is not the commit a push sends. A confirmation guards the machine only when what it covers is read, so what is asked has to be quick to read. The session that writes a series replays it on a machine that is thrown away and holds no credential, with no terminal to answer on. The tool runs under the maintainer's own `gh` login; a session that writes a series never holds a credential for it.

## Decision

A small tool, run by the maintainer under their own `gh` login, lands a series one pull request at a time. Claude hands it a series and never holds a credential.

- **Each layer is a local branch, `series/<slug>`, holding only its own commits.** A layer is a pull request: the number of the patch naming scheme is the layer, and each letter is a commit in it, so the commits that share a number share a branch slug and one slug belongs to one number. The branches form a chain, the first on `main` and each next on the last commit of the one before. A layer is pushed as built, opened as an ordinary pull request against `main`, run once, and merged with a merge commit using `gh pr merge --admin`. The merge commit brings the layer's commits into `main`, so the next layer's pull request shows only its own commits. A single-commit layer keeps that commit's subject and body as the pull request's title and body; a layer of several takes the first commit's subject as the title and lists the subjects as the body. Several commits keep each change's own blame and history, so a layer is not squashed, and the author keeps the number of commits small.
- **Layers land in id order.** The input is one plain-text file: a manifest followed by the patches as a single mbox, so it can be read before it is applied. Each patch has an id in the existing letter scheme, which keeps ids in the order the patches were written, and a branch slug; a number with two slugs, or a slug on two numbers, is refused. A fix or an inserted commit or layer is a small file holding only the new patches, and the tool takes several files, so nothing already delivered is regenerated.
- **State comes from git.** A layer whose commits are in `main` is skipped, a remote branch already at the kept commit is not pushed again, and an open pull request is updated when its branch changed. The only record beside git is the one that shows a kept branch is unchanged, below.
- **Before pushing anything, the series is replayed** in order on a scratch worktree of `origin/main`, one `git am` per commit with every hook off, and the checks that need no Docker run at each state, including the project scope check with its base set, for each layer, to the state before that layer's pull request: the tip of the pull request before it in the run, or `main` for the first one applied. The check then judges the pull request's own commits against the scope the earlier pull requests leave, as CI will once they have merged, and never against a widening in its own commits. A scope failure shows as a widening that is missing from the series, or that sits in the same pull request as the layer that needs it, before a pull request exists. Unless the run is a `--dry-run`, it then leaves the layers as the local branches above for the maintainer to review, and records beside the repository's git directory the first and last commit and the patches each was built from. A layer with only some of its commits already in `main` is refused.
- **The replay is the commit stage and each push is the push stage.** The replay runs what committing each patch would run, the `pre-commit`-stage hooks, after every commit. Before it pushes a branch, `--land` runs the `pre-push`-stage hooks over the pull request's own commits, in a scratch worktree of the commit it is about to push and against the base as then fetched, which holds the pull requests before it. It does so whether or not the maintainer installed the git hooks, and then pushes with every hook off, so none runs twice and none runs on the clone's working tree. A hook that fails stops the run before that push, with the pull requests before it merged, as a failed push would.
- **A branch is pushed only as built.** `--land` pushes the kept branches and does not replay. It refuses a branch whose tip is not the recorded commit, one built from a patch other than the series file's, and one built on a tree other than `main`'s now; the run is then repeated without `--land`, which rebuilds the branches, and says whether the layer would still apply to `main` as it is now. A branch built on a commit that is in `main` but is not its tip, because the layer before it has just merged, is moved onto the tip before it is pushed: the same tree with the same author, dates and message, so the layers land on one line and what is pushed has the content that was reviewed. It compares nothing with a rebuilt commit, because a rebuilt commit differs from the kept one in its committer date.
- **The maintainer reviews each layer before it merges.** When a layer's pull request has its required checks green, the tool prints its address and waits for a confirmation. With no terminal, or no confirmation, it stops there and leaves the pull request open; a run started again with `--land` picks up from it, and a pull request whose branch is already at the kept commit is reused, not pushed again. A run started with `--yes` confirms every merge in it, though a commit on the stop list is still asked about in the replay.
- **The tool stops for the maintainer** when a commit changes `.githooks/`, the pre-commit configuration, a workflow, an action, `tools/`, or the Python dependencies (`pyproject.toml`, `uv.lock`), which `uv run` installs and runs, or `.claude/`, which the replay does not run and a coding agent opened in the clone does.
- **It asks once, before any check runs.** The replay first applies every commit with nothing run, then lists all the commits on the stop list with their files and line counts, offers the diff of those files, and takes one answer for the series. With no terminal it stops.
- **A dry run on a throwaway machine may answer in advance.** `--accept-stops` prints the same list and replays without asking, and the tool refuses it without `--dry-run`. It is for the machine a series is written on, which holds no credential. The tool cannot check that, and `--dry-run` limits what the run keeps, not what the series' code can do, so using it only there is a rule for whoever runs it.

## Alternatives considered

- **GitHub stacked pull requests, merged a layer at a time.** Needs `gh stack` (a preview) and its metadata, every lower branch carries its ancestors' commits, every merge reruns the layers above, and `stack/**` would have to return to the branch filter.
- **Plain pull requests chained on each other, retargeted to `main` as the one below merges.** No rebase and no rerun, but a branch still carries its ancestors' commits, and the scope check sees the project docs of a branch, not of `main`.
- **Opening independent layers together from a dependency graph.** It needs the author to state dependencies, since sharing no file does not prove independence, and the series and projects on record give it little to shorten.
- **A scope check against `main` for every layer, with a widening delivered and landed as a series of its own.** The tool stays as it was and the maintainer runs it twice for one change; the replay of the second file also has to run on a base that holds the first, and it keeps judging the cumulative changes of the run.
- **Teaching the scope check about a stack of bases.** It would put the series into the documentation tools, which already answer the question once given the right base.
- **Running the pre-push hooks in the replay.** The replay runs before any pull request merges, so a hook that judges a push against the default branch sees the changes of every layer up to the one replayed and needs a base of its own, and a failure comes before the first pull request exists at the price of whole-tree lint such as `ansible-lint` there, on a stage that is not the one that runs them.
- **Leaving the pre-push hooks to the clone.** They run only where the maintainer installed them, and pre-commit runs a hook on the working tree, which may be another commit than the one pushed.
- **Landing each pull request before replaying the next.** It would match CI exactly, but it gives up the guarantee that nothing is pushed before the whole series has replayed and passed.
- **Rebuilding each branch from its patch when landing.** It would push a commit nobody reviewed, and it cannot be compared with the kept one.
- **Asking as the replay reaches each such commit.** The question arrives partway through a long run, one commit at a time, with nothing on screen but file names, so it tends to be answered unread.
- **A pseudo-terminal that answers the prompt for a session.** It confirms in the same way as a flag while looking like a person, depends on the prompt's wording, and has to be copied from a doc each time.
- **`--accept-stops` on any run, or an environment variable.** A run that keeps branches or lands is one on the maintainer's machine, and a variable left set would answer without being seen.
- **Leaving `.claude/` off the list, since the replay runs nothing in it.** A kept branch can be checked out and a session opened on it before the pull request merges, so the commands it names would be read for the first time after they could have run.
- **A sandbox for the replay, so that nothing is asked.** It removes the need for the confirmation, but the hooks that run a container cannot run in it and a change to the dependencies needs the network. [ADR 0114 (Remote series landing)](../0114-landing-a-series-from-a-device-other-than-the-laptop/revision-000.md) builds one for its console.
- **Squash or rebase merges.** A squash drops the commits from `main`'s history, which [`branching.md`](../../topics/engineering/branching.md#promoting) rules out.

## Consequences

Each layer waits for its run before the next is opened, so a series of N layers takes N runs in turn. A pre-push hook that fails does so after the pull requests before it have merged, where the replay's checks fail before any pull request exists. A series is replayed again when `main` changes between the replay and the landing. Every commit is applied twice, once to find what to ask about and once to check it. A confirmation still rests on the maintainer reading what it lists. A tool and its tests are code to maintain. How to run it is in [`landing-a-series.md`](../../topics/engineering/landing-a-series.md).

## Invariants

- A layer reaches `main` only by a pull request merged with a merge commit.
- No layer is merged without the maintainer's confirmation at that layer, or `--yes` on the run.
- A layer's pull request holds only its own commits.
- A kept branch that has changed since the tool built it is never pushed.
- The pre-push hooks run on the commit before every push that sends something, and a push made by the tool runs no hook of the clone it is run from.
- Nothing is pushed before the whole series has replayed and passed the checks that need no Docker.
- A pull request's scope is read from the state before its own commits, never from them.
- The tool never runs a commit's changes to `.githooks/`, the pre-commit configuration, a workflow, an action, `tools/` or the Python dependencies without the maintainer's confirmation, except in a dry run given `--accept-stops`.
- No branch is kept that holds a change to `.claude/` the maintainer was not asked about.
- A run that keeps branches or lands never takes that confirmation from a flag.
- No credential other than the maintainer's own `gh` login is used, and none is given to a session that writes a series.

## Non-goals

- Opening layers in parallel.
- Widening the Admin bypass or changing the rulesets.
- Replacing `git am` as the way a series is written and checked.

## Validation

The tool's tests cover the manifest, the replay, the skip of a layer already in `main`, the kept branches, the pull request and merge steps against a stand-in `gh` that merges into a real repository, the review gate, the stop list, which is asked about once and before any check, the refusal of `--accept-stops` without `--dry-run`, and the pre-push hooks, which run on the commit pushed and not the working tree, stop the push when one fails, and leave a hook installed in the clone unrun. A replay test checks that a scope-style check sees, for each pull request, only that pull request's commits, and the same base for every commit of one pull request.

## Reconsideration triggers

- `--admin` is refused by the bypass from the command line.
- A required up-to-date rule is added to `main`.
- CI waits grow long enough that a series should be grouped into fewer, larger layers.
- Projects are planned with many independent stages.

## Revision notes

Revision 3 stopped only for code the replay and the checks run. This revision also stops for `.claude/`, which a coding agent opened in the clone runs.
