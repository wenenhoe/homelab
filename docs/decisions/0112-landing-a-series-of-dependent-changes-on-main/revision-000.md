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

## Decision

A small tool, run by the maintainer under their own `gh` login, lands a series one pull request at a time. Claude hands it a series and never holds a credential.

- **Each layer is a local branch, `series/<slug>`, holding only its own commits.** A layer is a pull request: the number in the patch naming scheme is the layer and each letter is a commit in it, so commits sharing a number share a slug and one slug belongs to one number. The branches form a chain, the first on `main` and each next on the last commit of the one before. A layer is pushed as built, opened as an ordinary pull request against `main`, and merged with a merge commit by `gh pr merge --admin`, so the next layer's pull request shows only its own commits. A single-commit layer keeps that commit's subject and body as the pull request's title and body; a layer of several takes the first subject as the title and lists the subjects as the body. A layer is not squashed, so each change keeps its blame, and the author keeps the number of commits small.
- **Layers land in id order.** The input is a plain-text file, a manifest followed by the patches as one mbox, so it can be read before it is applied. A number with two slugs, or a slug on two numbers, is refused. A fix or an inserted layer is a small file of only the new patches, and the tool takes several files.
- **State comes from git.** A layer whose commits are in `main` is skipped, a remote branch already at the kept commit is not pushed again, and an open pull request is updated when its branch changed. The only other record shows that a kept branch is unchanged.
- **The series is replayed before anything is pushed**, in order on a scratch worktree of `origin/main`: one `git am` per patch with the views reset between, and the checks that need no Docker at each state, including the project scope check with its base set to `main`, so a missing widening shows before a pull request exists. Unless the run is a `--dry-run` it leaves the layers as the local branches above and records each one's first and last commit and the patches it was built from. A layer with only some of its commits in `main` is refused.
- **A branch is pushed only as built.** `--land` replays nothing. It refuses a branch whose tip is not the recorded commit, one built from other patches than the file's, and one built on a tree other than `main`'s now. A branch built on a commit that is in `main` but no longer its tip, because the layer before it just merged, is moved onto the tip with the same trees, authors, dates and messages.
- **The maintainer confirms each layer.** When a layer's required checks are green the tool prints its address and waits. With no terminal or no confirmation it leaves the pull request open, and a later `--land` continues from it. `--yes` confirms every merge in the run, though a layer on the stop list is still asked about in the replay.
- **The tool stops for the maintainer** when a layer changes `.githooks/`, the pre-commit configuration, a workflow, an action, `tools/`, or the Python dependencies (`pyproject.toml`, `uv.lock`).

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

## Reconsideration triggers

- `--admin` is refused by the bypass from the command line.
- A required up-to-date rule is added to `main`.
- CI waits grow long enough that a series should be grouped into fewer, larger layers.
- Projects are planned with many independent stages.
