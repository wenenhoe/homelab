---
id: ADR-0112
revision: 0
type: adr
title: Landing a series of dependent changes on main
short: Landing a patch series
solution: A maintainer-run tool lands a series one pull request at a time, each from a fresh branch off main, replaying the series first and merging each layer with the admin bypass
summary: How a series of patches reaches main as pull requests when main refuses any update outside a merged pull request and a pull request based on another branch sees neither main's project docs nor a stable head.
topic: repository-tooling
status: approved
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
- Past series are rare: 8 of 86 merged pull requests are layers, in two series. Layers that share no file can still depend on each other, and layers that each flip a row in one project doc conflict when applied independently. Most open projects' stages are chains, with a handful of independent ones.

**Threat model.** The asset is `main`, which the CD agent deploys. A tool that applies a series replays patches and runs the hooks on the maintainer's machine, so a patch that changes the code the replay runs would execute before CI sees it. The tool runs under the maintainer's own `gh` login; a session that writes a series never holds a credential for it.

## Decision

A small tool, run by the maintainer under their own `gh` login, lands a series one pull request at a time. Claude hands it a series and never holds a credential.

- **Each layer is a branch made fresh from the current `main`**, with only its own patch applied, opened as an ordinary pull request against `main`, run once, and merged with a merge commit using `gh pr merge --admin`. The next branch is made from `main` after that merge.
- **Layers land in id order.** The input is one plain-text file: a manifest followed by the patches as a single mbox, so it can be read before it is applied. Each layer has an id in the existing letter scheme and a branch slug; an `after:` or `before:` id places an inserted layer. A fix or an inserted layer is a small file holding only the new layer, and the tool takes several files, so nothing already delivered is regenerated.
- **State comes from git.** A layer whose commits are in `main` is skipped, and an open pull request is replaced if its patch changed. No state file.
- **Before pushing anything, the series is replayed** in order on a scratch worktree of `origin/main`, one `git am` per patch with the views reset between, and the checks that need no Docker run at each state, including the project scope check with its base set to `main`. A scope failure then shows as a missing widening layer, before a pull request exists.
- **The maintainer reviews each layer before it merges.** When a layer's pull request has its required checks green, the tool prints its address and waits for a confirmation. With no terminal, or no confirmation, it stops there and leaves the pull request open; a run started again picks up from it, and a pull request whose branch already holds the same patch on the same base is reused, not pushed again. A run started with `--yes` confirms every merge in it, though a layer on the stop list is still asked about first.
- **The tool stops for the maintainer** when a layer changes `.githooks/`, the pre-commit configuration, a workflow, an action, `tools/`, or the Python dependencies (`pyproject.toml`, `uv.lock`), which `uv run` installs and runs.

## Alternatives considered

- **GitHub stacked pull requests, merged a layer at a time.** Needs `gh stack` (a preview) and its metadata, every lower branch carries its ancestors' commits, every merge reruns the layers above, and `stack/**` would have to return to the branch filter.
- **Plain pull requests chained on each other, retargeted to `main` as the one below merges.** No rebase and no rerun, but a branch still carries its ancestors' commits, and the scope check sees the project docs of a branch, not of `main`.
- **Opening independent layers together from a dependency graph.** It needs the author to state dependencies, since sharing no file does not prove independence, and the series and projects on record give it little to shorten.
- **Squash or rebase merges.** A squash drops the commits from `main`'s history, which [`branching.md`](../../topics/engineering/branching.md#promoting) rules out.

## Consequences

Each layer waits for its run before the next branch exists, so a series of N layers takes N runs in turn. A tool and its tests are code to maintain. The tool's use is described in a topic doc once it exists.

## Invariants

- A layer reaches `main` only by a pull request merged with a merge commit.
- No layer is merged without the maintainer's confirmation at that layer, or `--yes` on the run.
- A branch holds only its own layer's commits.
- Nothing is pushed before the whole series has replayed and passed the checks that need no Docker.
- The tool never runs a layer's changes to `.githooks/`, the pre-commit configuration, a workflow, an action, `tools/` or the Python dependencies without the maintainer's confirmation.
- No credential other than the maintainer's own `gh` login is used, and none is given to a session that writes a series.

## Non-goals

- Opening layers in parallel.
- Widening the Admin bypass or changing the rulesets.
- Replacing `git am` as the way a series is written and checked.

## Validation

The tool's tests cover the manifest, the replay, the skip of a layer already in `main`, the pull request and merge steps against a stand-in `gh` that merges into a real repository, and the review gate; the stop list is a test over the paths that stop it.

## Reconsideration triggers

- `--admin` is refused by the bypass from the command line.
- A required up-to-date rule is added to `main`.
- CI waits grow long enough that a series should be grouped into fewer, larger layers.
- Projects are planned with many independent stages.
