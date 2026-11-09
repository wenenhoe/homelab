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
- **Parallel layers share the project doc.** Every stage flips its row in the Execution plan table. In the five-layer series that closed the integration-records project, each of layers 2 to 4 failed `git apply --check` against the state without the layer before it, on the table's adjacent lines, so applying them independently conflicts there.
- **Series are rare and mostly dependent.** Eight of the 86 merged pull requests are layers, in two series. In the five-layer one every layer edits that project doc and most share a code or doc file with another. The three-layer one touched three disjoint file sets, yet its last layer links to the file its second creates, so sharing no file did not make it independent.
- **The stage tables of the open projects are mostly chains.** Of the 36 project docs, 32 have two or more stages (147 in all). Most open with a stage that settles assumptions or approves the decision and widens `allowed_paths`, and each later stage builds on the one before (`backup-archive-signing`, `kms-image`, `coding-agent-management`); the order is often already written in a stage's prose ("starts once…"). Skimming the tables, the stages that look independent are a handful: the first three of `bind-mounted-config-files` (the Caddyfile, three services' files, the SeaweedFS identity file) and the three hosts of `host-hardening-remaining-hosts`, and each has a closing or gating stage that waits on them. A series is also usually part of a project, not all of it, since a project's stages merge over weeks (`opnsense-config` has 23).

`gh pr merge` has an `--admin` flag for a pull request that does not meet its requirements, and the `main` ruleset has no "require branches to be up to date" rule, so a layer need not be rebased after the one below merges. Still to check: that `--admin` is accepted against the `main-review` bypass on this repository, which only a merge shows.

## Options

- **GitHub stacked pull requests, merged a layer at a time.** What is done now. Needs `gh stack` (a preview) and its stack metadata, the lower branches carry their ancestors' commits, and every merge reruns the layers above. Revert is clean only because layers are merged one at a time.
- **Plain pull requests chained on each other, retargeted to `main` as the one below merges.** No rebase and no rerun, since the head SHA never changes. A branch still carries its ancestors' commits, and the scope check sees the project docs of a branch, not of `main`.
- **One pull request at a time, each branch made fresh from `main`.** After a layer merges, the next branch is created from the current `main` and the next patch applied to it, so a branch holds only its own commits, the pull request is an ordinary one against `main`, the scope check sees exactly what has landed, and each layer runs once. Costs waiting for each run in turn.
- **The same, with a dependency graph.** Layers with nothing unmet are opened together, each from `main`, and dependent ones wait. Needs the author to state the dependencies, since sharing no file does not prove independence, and it shortens the wait only where layers are really independent. Past series and the open projects give it little to shorten: a handful of projects have two or three independent stages, and layers that all flip a row in one project doc conflict when opened together.
- **Squash or rebase merges.** Rejected before it starts: a squash drops the commits from `main`'s history, which [`branching.md`](../topics/engineering/branching.md#promoting) rules out.

## Leaning

One pull request at a time from a fresh branch, in order, done by a small tool run by the maintainer under their own `gh` login. Claude would hand it a series and never hold a credential.

- **Input:** one plain-text file, a manifest followed by the patches as a single mbox, so it can be read before it is applied. Each layer has an id in the existing letter scheme and a branch slug, and layers land in id order; an `after:` or `before:` id places an inserted layer. A fix or an inserted layer is a small file holding only the new layer, and the tool takes several files, so nothing already delivered is regenerated.
- **State comes from git:** a layer whose commits are in `main` is skipped, an open pull request is replaced if its patch changed. No state file.
- **Before pushing anything,** replay the layers in order on a scratch worktree of `origin/main`, one `git am` per patch, and run the checks that need no Docker, including the project scope check with the base set to `main`. A scope failure then shows up as a missing widening layer, before the pull request exists.
- **Stop for the maintainer** when a layer changes `.githooks/`, the pre-commit configuration, a workflow, an action or `tools/`: the replay and the hooks run that code on the maintainer's machine before CI sees it.

Choosing either of the first two options means adding `stack/**` back to the filter. What would change this: a failed `--admin` merge from the command line, a required up-to-date rule added to `main`, CI waits long enough that the series should be grouped into fewer, larger layers instead, or projects being planned with many independent stages, which would make a dependency graph pay for itself.
