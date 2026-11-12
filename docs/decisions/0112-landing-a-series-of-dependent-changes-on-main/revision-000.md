---
id: ADR-0112
revision: 0
type: adr
title: Landing a series of dependent changes on main
short: Landing a patch series
solution: A maintainer-run tool lands a series one pull request at a time, each from a fresh branch off main, replaying the series first and merging each layer with the admin bypass
summary: How a series of patches reaches main as pull requests when main refuses any update outside a merged pull request and a pull request based on another branch sees neither main's project docs nor a stable head.
topic: repository-tooling
status: superseded
superseded_by: 1
related: [ADR-0076]
---

# 0112. Landing a series of dependent changes on main

## Problem

Work is written as a series of patches, and a project's stages are each meant to be one pull request, so a series is the normal shape of a change. Landing one by hand is slow. What has to be true: each layer reaches `main` as its own pull request with a merge commit, so one layer can be reverted alone; every check runs on a layer against the state `main` will be in; a failure that only the order of layers causes shows before a pull request exists; and no credential other than the maintainer's own can merge to `main`.

## Context

- `main` accepts a change only through a pull request merged with the Admin bypass, and the `main-review` ruleset's `update` rule refuses every other actor ([`branching.md`](../../topics/engineering/branching.md#the-rulesets), [ADR 0076 (Branch separation)](../0076-keeping-what-production-runs-apart-from-work-in-progress/revision-000.md)). GitHub's stacked pull requests merge a whole stack as one update, which that rule refuses. Merging one pull request at a time with the bypass works. `gh pr merge --admin --merge` merges a pull request into `main` through that bypass from the command line, and `main` has no "require branches to be up to date" rule.
- A stacked layer is based on the branch below it. The `pull_request` branch filter lists no `stack/**`, so an upper layer gets no run and its required checks never report. GitHub rebases the remaining layers after each merge, each with a new head SHA and a full run, which for N layers merged one at a time is N(N-1)/2 extra runs. The runs cost waiting, not money, on a public repository's hosted runners.
- The project scope check judges a pull request against the project docs as they stood on its base, so a layer that needs a widened `allowed_paths` fails until the widening has merged, and a pull request based on another branch does not see a widening that is only there.
- `git am` runs hooks that regenerate the generated views ([`.githooks/`](../../../.githooks)) and leave them unstaged, so a second patch in one invocation fails. One patch per invocation, with the views reset between, avoids it.
- Series are rare, and most projects' stages are chains. Layers that share no file can still depend on each other, and layers that each flip a row in one project doc conflict when applied independently.

**Threat model.** The asset is `main`, which the CD agent deploys. A tool that applies a series replays patches and runs the hooks on the maintainer's machine, so a patch that changes the code the replay runs would execute before CI sees it. The tool runs under the maintainer's own `gh` login; a session that writes a series never holds a credential for it.

## Decision

A small tool, run by the maintainer under their own `gh` login, lands a series one pull request at a time. Claude hands it a series and never holds a credential.

- **Each layer is a local branch, `series/<slug>`, holding only its own commits.** A layer is a pull request: the number of the patch naming scheme is the layer, and each letter is a commit in it, so the commits that share a number share a branch slug and one slug belongs to one number. The branches form a chain, the first on `main` and each next on the last commit of the one before. A layer is pushed as built, opened as an ordinary pull request against `main`, run once, and merged with a merge commit using `gh pr merge --admin`. The merge commit brings the layer's commits into `main`, so the next layer's pull request shows only its own commits. A single-commit layer keeps that commit's subject and body as the pull request's title and body; a layer of several takes the first commit's subject as the title and lists the subjects as the body. Several commits keep each change's own blame and history, so a layer is not squashed, and the author keeps the number of commits small.
- **Layers land in id order.** The input is one plain-text file: a manifest followed by the patches as a single mbox, so it can be read before it is applied. Each patch has an id in the existing letter scheme, which keeps ids in the order the patches were written, and a branch slug; a number with two slugs, or a slug on two numbers, is refused. A fix or an inserted commit or layer is a small file holding only the new patches, and the tool takes several files, so nothing already delivered is regenerated.
- **State comes from git.** A layer whose commits are in `main` is skipped, a remote branch already at the kept commit is not pushed again, and an open pull request is updated when its branch changed. The only record beside git is the one that shows a kept branch is unchanged, below.
- **Before pushing anything, the series is replayed** in order on a scratch worktree of `origin/main`, one `git am` per patch with the views reset between, and the checks that need no Docker run at each state, including the project scope check with its base set to `main`. A scope failure then shows as a missing widening layer, before a pull request exists. Unless the run is a `--dry-run`, it then leaves the layers as the local branches above for the maintainer to review, and records beside the repository's git directory the first and last commit and the patches each was built from. A layer with only some of its commits already in `main` is refused.
- **A branch is pushed only as built.** `--land` pushes the kept branches and does not replay. It refuses a branch whose tip is not the recorded commit, one built from a patch other than the series file's, and one built on a tree other than `main`'s now; the run is then repeated without `--land`, which rebuilds the branches, and says whether the layer would still apply to `main` as it is now. A branch built on a commit that is in `main` but is not its tip, because the layer before it has just merged, is moved onto the tip before it is pushed: the same tree with the same author, dates and message, so the layers land on one line and what is pushed has the content that was reviewed. It compares nothing with a rebuilt commit, because the generated views carry the date of the apply and a rebuilt commit differs from the kept one in content nobody changed.
- **The maintainer reviews each layer before it merges.** When a layer's pull request has its required checks green, the tool prints its address and waits for a confirmation. With no terminal, or no confirmation, it stops there and leaves the pull request open; a run started again with `--land` picks up from it, and a pull request whose branch is already at the kept commit is reused, not pushed again. A run started with `--yes` confirms every merge in it, though a layer on the stop list is still asked about in the replay.
- **The tool stops for the maintainer** when a layer changes `.githooks/`, the pre-commit configuration, a workflow, an action, `tools/`, or the Python dependencies (`pyproject.toml`, `uv.lock`), which `uv run` installs and runs.

## Alternatives considered

- **GitHub stacked pull requests, merged a layer at a time.** Needs `gh stack` (a preview) and its metadata, every lower branch carries its ancestors' commits, every merge reruns the layers above, and `stack/**` would have to return to the branch filter.
- **Plain pull requests chained on each other, retargeted to `main` as the one below merges.** No rebase and no rerun, but a branch still carries its ancestors' commits, and the scope check sees the project docs of a branch, not of `main`.
- **Opening independent layers together from a dependency graph.** It needs the author to state dependencies, since sharing no file does not prove independence, and the series and projects on record give it little to shorten.
- **Rebuilding each branch from its patch when landing.** It would push a commit nobody reviewed, and it cannot be compared with the kept one.
- **Squash or rebase merges.** A squash drops the commits from `main`'s history, which [`branching.md`](../../topics/engineering/branching.md#promoting) rules out.

## Consequences

Each layer waits for its run before the next is opened, so a series of N layers takes N runs in turn. A series is replayed again when `main` changes between the replay and the landing. A tool and its tests are code to maintain. How to run it is in [`landing-a-series.md`](../../topics/engineering/landing-a-series.md).

## Invariants

- A layer reaches `main` only by a pull request merged with a merge commit.
- No layer is merged without the maintainer's confirmation at that layer, or `--yes` on the run.
- A layer's pull request holds only its own commits.
- A kept branch that has changed since the tool built it is never pushed.
- Nothing is pushed before the whole series has replayed and passed the checks that need no Docker.
- The tool never runs a layer's changes to `.githooks/`, the pre-commit configuration, a workflow, an action, `tools/` or the Python dependencies without the maintainer's confirmation.
- No credential other than the maintainer's own `gh` login is used, and none is given to a session that writes a series.

## Non-goals

- Opening layers in parallel.
- Widening the Admin bypass or changing the rulesets.
- Replacing `git am` as the way a series is written and checked.

## Validation

The tool's tests cover the manifest, the replay, the skip of a layer already in `main`, the kept branches, the pull request and merge steps against a stand-in `gh` that merges into a real repository, and the review gate; the stop list is a test over the paths that stop it.

## Reconsideration triggers

- `--admin` is refused by the bypass from the command line.
- A required up-to-date rule is added to `main`.
- CI waits grow long enough that a series should be grouped into fewer, larger layers.
- Projects are planned with many independent stages.
