---
id: EXP-landing-a-patch-series-as-pull-requests
title: "How should a series of patches reach main as pull requests?"
type: exploration
status: open
summary: "Whether a series of dependent changes should land as GitHub stacked pull requests or as one independent pull request at a time, what each costs in CI runs and revert safety, and what a tool that lands a series would take as input and check first."
topic: repository-tooling
related: [ADR-0076]
---

# How should a series of patches reach main as pull requests?

Work is written as a series of patches, applied with `git am` and landed as pull requests into `main`. A project's stages are each meant to be one pull request, so a series is the normal shape of a change. Landing one by hand is slow, and GitHub's stacked pull requests, which would speed it up, do not fit this repo's rulesets. What has to be decided is how a series reaches `main`, and whether a tool does it.

## What bears on it

- **The atomic stack merge is refused.** `gh stack merge` and the web button both fail on `main`: the `main-review` ruleset's `update` rule refuses every update by an actor not on its bypass list, and the Admin bypass is limited to pull requests ([`branching.md`](../topics/engineering/branching.md#the-rulesets), [ADR 0076 (Branch separation)](../decisions/0076-keeping-what-production-runs-apart-from-work-in-progress/revision-000.md)). Widening the bypass would remove the property that a credential can merge but not push, which that decision chose on purpose. Merging one pull request at a time with the bypass works.
- **A stacked layer is based on the branch below it.** Observed on a throwaway repository with `gh stack` 0.3.0: an upper layer's `base.ref` is its parent branch, so the `pull_request` branch filter has to list `stack/**` or that layer gets no run and its required checks never report. The filter does not list it: the only options that open a pull request against another branch are the first two below. `detect-changes` diffs base to head, so each layer is scoped to its own changes.
- **GitHub rebases the remaining layers after each merge.** Each gets a new head SHA and one full run, so a stack of N layers merged one at a time costs N(N-1)/2 extra runs. The runs are free on a public repository's hosted runners; the cost is waiting and waste, not money.
- **A merge commit keeps a layer revertible.** `git revert -m 1` on a layer's merge commit undoes that layer's diff against `main` only, as long as each layer is merged on its own. One merge commit for a whole stack reverts all of it.
- **The project scope check judges a pull request against the project docs as they stood on the base.** A layer that needs a widened `allowed_paths` fails until the widening has merged, and a pull request based on another branch does not see a widening that is only there.
- **`git am` runs hooks that regenerate the generated views** ([`.githooks/`](../../.githooks)). They leave the views unstaged, so a second patch in the same invocation fails with "does not match index". One patch per invocation, with the views reset between, avoids it.
- **Parallel layers share the project doc.** Every stage flips its row in the Execution plan table, and rows on adjacent lines conflict when two layers are applied independently. Not yet tried.

Still to check: whether `gh pr merge` with the Admin bypass is accepted for a single pull request from the command line (the web button is), whether a required "up to date" rule is set on `main`, and the share of series that have genuinely independent layers.

## Options

- **GitHub stacked pull requests, merged a layer at a time.** What is done now. Needs `gh stack` (a preview) and its stack metadata, the lower branches carry their ancestors' commits, and every merge reruns the layers above. Revert is clean only because layers are merged one at a time.
- **Plain pull requests chained on each other, retargeted to `main` as the one below merges.** No rebase and no rerun, since the head SHA never changes. A branch still carries its ancestors' commits, and the scope check sees the project docs of a branch, not of `main`.
- **One pull request at a time, each branch made fresh from `main`.** After a layer merges, the next branch is created from the current `main` and the next patch applied to it, so a branch holds only its own commits, the pull request is an ordinary one against `main`, the scope check sees exactly what has landed, and each layer runs once. Costs waiting for each run in turn.
- **The same, with a dependency graph.** Layers with nothing unmet are opened together, each from `main`, and dependent ones wait. Needs the author to state the dependencies, since sharing no file does not prove independence, and it shortens the wait only where layers are really independent.
- **Squash or rebase merges.** Rejected before it starts: a squash drops the commits from `main`'s history, which [`branching.md`](../topics/engineering/branching.md#promoting) rules out.

## Leaning

One pull request at a time from a fresh branch, with a dependency graph where layers are independent, done by a small tool run by the maintainer under their own `gh` login. Claude would hand it a series and never hold a credential.

- **Input:** one plain-text file, a manifest followed by the patches as a single mbox, so it can be read before it is applied. Each layer has an id in the existing letter scheme, a branch slug and optionally `after:` or `before:` ids; with none, a layer follows the previous id. A fix or an inserted layer is a small file holding only the new layer, and the tool takes several files, so nothing already delivered is regenerated.
- **State comes from git:** a layer whose commits are in `main` is skipped, an open pull request is replaced if its patch changed. No state file.
- **Before pushing anything,** replay the layers in order on a scratch worktree of `origin/main`, one `git am` per patch, and run the checks that need no Docker, including the project scope check with the base set to `main`. A scope failure then shows up as a missing widening layer, before the pull request exists.
- **Stop for the maintainer** when a layer changes `.githooks/`, the pre-commit configuration, a workflow, an action or `tools/`: the replay and the hooks run that code on the maintainer's machine before CI sees it.

Choosing either of the first two options means adding `stack/**` back to the filter. What would change this: a failed bypass merge from the command line, a required up-to-date rule on `main`, or CI waits long enough that the series should be grouped into fewer, larger layers instead.
