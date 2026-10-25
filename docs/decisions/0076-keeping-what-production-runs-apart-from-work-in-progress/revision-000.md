---
id: ADR-0076
revision: 0
type: adr
title: Keeping what production runs apart from work in progress
short: Branch separation
solution: Three long-lived branches, where only main is deployed, Renovate and development each collect on their own branch, and each reaches main by a pull request that lists what to run
summary: How dependency updates and long-running development can wait on branches of their own while main stays the exact state the CD agent deploys.
topic: deployment-platform
status: accepted
related: [ADR-0037, ADR-0044, ADR-0050, ADR-0064]
---

# 0076. Keeping what production runs apart from work in progress

## Problem

`main` is both the state production deploys and the place every change lands first. Two things follow that the maintainer does not want. Merging a series of Renovate pull requests is a series of deploys, one per merge, whatever state the series is in. And unfinished development cannot sit anywhere but a pull request, so a dependency update that is ready has no way to reach production without it or after it.

What has to be true: `main` moves only when the maintainer decides it should; a batch of dependency updates can be released without unfinished development; every check that runs today runs on a change before it can reach `main`; and the person promoting a change can see what that promotion requires them to run.

## Context

[ADR 0044 revision 0-c (CD agent trigger)](../0044-prod-automation-trigger-and-execution/revision-000-c.md)'s deploy job fetches `origin/main` every few minutes and runs when the commit differs from the last one it deployed. `tools/cd_agent/run_job.py` names the branch once, as `BRANCH = "main"`. Merging to `main` is therefore a deploy within the poll interval, and nothing else in the repository is deployed from any other ref.

Renovate runs daily and opens pull requests against the default branch, in the Monday and Thursday window of `renovate.json5`'s `schedule`. A review of several is several merges.

The repository merges pull requests with merge commits. A promotion by merge commit leaves every promoted commit an ancestor of `main`; a squash merge leaves the content in `main` and the commits off it.

An image this repository builds is published only after the merge that publishes it, and compose files pin its tag ([`gates.md`](../../topics/engineering/ci/gates.md#dockerfile-changes)). A Dockerfile edit that keeps its version tag changes the image behind that tag.

A Renovate branch is cut on top of the commits `maintenance` holds that `main` does not. Renovate marks a pull request edited when any commit between its base branch and its branch has an author or committer other than its own, and then neither rebases nor updates it, whatever `rebaseWhen` says. Rewriting `maintenance` therefore leaves old copies of those commits in every open Renovate branch, committed by whoever ran the rewrite, and blocks every one of those pull requests. Merging `main` into `maintenance` leaves them as they are: Renovate rebases its own branches onto the merged tip under `rebaseWhen: behind-base-branch`, without marking them edited. A plain `git rebase` also drops merge commits, so a replayed branch can lose the promotions on it.

A ruleset can require a pull request and passing checks on a branch and still let a named actor push to it, listing the bypassed rules in the push output; that actor can be allowed to force-push `maintenance` and `develop` and refused on `main`. The job token a workflow gets by default is refused on all three, so the Renovate workflow needs a credential of its own to push. A ruleset can require approving reviews on a branch, but an approval from a GitHub App with pull request access counts towards them, so an app that can approve can then merge. A ruleset's update rule refuses every change to a branch, a pull request merge included, to any actor not on its bypass list; a bypass list limited to pull requests lets its actor merge a pull request and still refuses them a direct push. A rule in a ruleset with no bypass list holds for every actor, an administrator included, while one in a ruleset with a bypass list can be bypassed by the actors on it, a force push and a branch deletion among them. Deleting a head branch on merge acts as the merging actor, so it removes a branch that a bypassable deletion rule covers. A GitHub App installation token acts as the app, a bot identity separate from the maintainer's account. Caches saved on `main` restore in pull requests into the other branches.

A deploy whose command fails is not recorded, so the CD agent runs it again on its next poll. A compose pin that reaches `main` before its image is published therefore fails and retries until the image exists.

**Threat model.** The adversary can merge or push to a branch other than `main`, holds the credential the Renovate workflow uses, or is a dependency source that sends a malicious update. The asset is what the CD agent deploys. A credential that can write to `maintenance` can also open a pull request into `main`, so if that credential could also merge one, it would deploy without the maintainer having looked at it. A required review does not prevent that, because the credential's own approval counts. If any ref but `main` could be deployed, a merge there would act on production as a merge to `main` does now, with none of the promotion review. If images were published from branches other than `main`, an unpromoted Dockerfile change could replace the image behind a version tag that production pulls.

## Decision

This diagram shows where changes land, how they are promoted and how the branches are realigned as this revision decided it, not what runs now.

```mermaid
flowchart LR
    R[Renovate] -->|opens pull requests| M[maintenance]
    DEV[Development] -->|pull requests| D[develop]
    FIX["A fix that cannot wait"] -->|"its own pull request"| P
    M -->|"promotion pull request, merge commit"| P["main: production"]
    D -->|"promotion pull request, merge commit"| P
    P -->|"realigned by the Renovate workflow: fast-forward, or main merged in"| M
    P -->|"realigned by the maintainer: fast-forward, or main merged in"| D
    P -->|"fetched and deployed; no other ref is"| CD[CD agent]
```

- **Branches.** `main` is production. `maintenance` collects dependency updates. `develop` collects development. All three are long-lived. Only `main` is deployed: the CD agent, its jobs and ADR 0044 are unchanged, and no other ref is fetched by it.
- **Where changes land.** Renovate targets `maintenance` (`baseBranchPatterns`). Development pull requests target `develop`. A fix that cannot wait goes to `main` in its own pull request, and both other branches are then realigned.
- **Promotion.** A pull request from `maintenance` or `develop` into `main`, merged by the maintainer with a merge commit. The two promote independently, so a batch of dependency updates does not wait for development.
- **Realignment never rewrites a branch.** After `main` moves, a branch that is an ancestor of `main` is fast-forwarded to it, which a promotion by merge commit makes `maintenance` and `develop`. A branch with commits not yet promoted has `main` merged into it with a plain merge commit. Both are pushed without force. A merge that conflicts is aborted, leaving the branch as it was.
- **`maintenance` is realigned before each Renovate run.** The first step of the Renovate workflow realigns `maintenance` as above, so Renovate reads the repository, its configuration included, as `main` has it plus the dependency updates still waiting. Renovate runs with `rebaseWhen: behind-base-branch` so its open branches follow. A merge that conflicts fails the workflow before Renovate runs. The logic is stdlib-only Python under `tools/ci` with unit tests ([ADR 0064 (CI and doc check code)](../0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md)). `develop` is realigned by the maintainer, as it holds work in progress that nothing else may touch.
- **Checks.** Every pull request runs the checks it runs today, whichever of the three branches it targets. A ruleset on each branch requires them; `main` accepts only pull requests, refuses every update by an actor not on its bypass list and refuses force pushes; `maintenance` and `develop` can be neither deleted nor force-pushed by anyone, the maintainer and the app included, by rules in a ruleset with no bypass list.
- **Who can push.** The Renovate workflow authenticates as a GitHub App installed on this repository alone, an identity used for nothing else. The app may push to `maintenance` and open pull requests, and is not on the bypass list of `main`, whose update rule refuses it every change there, so it cannot merge into `main` whoever approves. `maintenance` and `develop` accept pushes without a pull request from the maintainer and the app. The maintainer is on the bypass list of `main` for pull requests only, which lets them merge a promotion they opened themselves, and still refuses them a direct push.
- **Promotion checklist.** A workflow on pull requests into `main` computes, from the diff between `main` and the pull request's head, what has to be run once it merges, and writes it into the pull request description between markers, leaving the maintainer's own text alone. Each rule names a path pattern and the command it asks for. The mapping is stdlib-only Python under `tools/ci` with unit tests ([ADR 0064 (CI and doc check code)](../0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md)). The checklist is advisory and never gates a merge.
- **Images.** Built and published from `main` only, as now.
- **Docs.** A topic doc describes the branch it is on. The docs on `main` describe what runs.

## Alternatives considered

- **One integration branch beside `main`.** Dependency updates and development would share it, so releasing the updates would release whatever development was on it. The separation the maintainer wants is between those two, not only between them and `main`.
- **A settle delay in the CD agent.** It would hold a deploy until `main` has been quiet for a while. It changes ADR 0044's trigger, still deploys once a review pauses, and does nothing for development.
- **Realigning only by hand, after a promotion.** It leaves `maintenance` behind `main` whenever `main` moves some other way, such as a fix straight to `main` or a promotion of `develop`, and Renovate then proposes updates against files `main` has since changed.
- **Rebasing or resetting `maintenance` onto `main`.** It keeps history linear, but it blocks every open Renovate pull request, and a plain rebase drops promotion merge commits.
- **A staging branch the CD agent also follows.** There is no second environment to deploy it to.
- **Publishing images from `maintenance` and `develop`.** It would have a promoted pin's image exist before `main` moves, but an unpromoted Dockerfile change could replace the image behind a version tag that production pulls.
- **Grouping Renovate pull requests harder.** It lowers the number of merges, not the fact that each is a deploy.

## Consequences

- `develop` is realigned by hand after every promotion and fix to `main`. `maintenance` is realigned by the Renovate workflow.
- Each realignment of a branch with unpromoted commits leaves a merge commit on it.
- A merge that conflicts holds back that day's Renovate run until the maintainer resolves it.
- The Renovate credential becomes an app installation token the workflow mints on each run, in place of a long-lived personal one.
- A promotion pull request opened by the maintainer is merged by the maintainer through the bypass; the update rule is what stops any other identity doing so.
- Renovate rebases its own open pull requests onto the realigned `maintenance`. A pull request closed unmerged is not reopened for the same version.
- A pull request into `develop` needs no rebase after a realignment, since the branch is never rewritten.
- A dependency update reaches production only when the maintainer promotes `maintenance`, so a security update waits for a promotion, or goes straight to `main`.
- The checklist stays only until the CD agent applies every kind of change itself.

## Invariants

- The CD agent fetches `main` and no other ref.
- No change reaches `main` without a pull request that passed the checks.
- No force push reaches `main`.
- No credential that can push to `maintenance` or `develop` can also merge into `main`.
- No image is published from a branch other than `main`.
- No branch is rewritten, and no realignment pushes with force.
- A realignment never changes `main`.
- Renovate does not run against a `maintenance` that failed to realign.

## Non-goals

- A second environment, or a deploy from `maintenance` or `develop`.
- A required review or a second reviewer. An approval from the app counts, so a review does not stop a credential merging, and a sole maintainer cannot approve their own pull request; the update rule stops a credential merging, and the maintainer's bypass keeps promotions a one-person flow.
- Automating the realignment of `develop`.
- A promotion checklist that applies changes.
- Changing how Renovate groups or schedules its pull requests.
- Restricting which files the app may change on `maintenance`.

## Validation

- The checklist rules are unit-tested against diffs of the paths they name.
- Realignment is tested on temporary repositories: a branch that is an ancestor of `main` is fast-forwarded, one with extra commits gets `main` merged in with those commits intact, and a conflicting one is left unchanged with a failure.
- A test over the workflow triggers asserts that the checks which run on a pull request into `main` also run on one into `maintenance` or `develop`.
- Once the ruleset is set, the maintainer attempts, as the app, to merge a pull request into `main` and to push to it, and as themselves to push to `main` directly; all three are refused, and the app's approval of a pull request does not let it merge that one either. A pull request from `maintenance` is merged by the maintainer.

## Reconsideration triggers

- A second environment to deploy to.
- A second maintainer, which makes a real review of promotions possible.
- Promotions routinely needing both branches at once.
- The CD agent applying every kind of change itself, which retires the checklist.
