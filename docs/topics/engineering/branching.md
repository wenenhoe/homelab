# Branches and promotion

The repository has three long-lived branches ([ADR 0076 (Branch separation)](../../decisions/0076-keeping-what-production-runs-apart-from-work-in-progress/revision-000.md)). Only `main` is deployed: the CD agent fetches it every few minutes and deploys when its commit changes ([`cd-agent-runner.md`](../deploy/cd-agent-runner.md)), and it fetches no other ref.

| Branch | Holds | Who writes to it | Deployed |
| :--- | :--- | :--- | :--- |
| `main` | What production runs. | The maintainer, through a pull request merged with a bypass. Nobody pushes to it. | Yes |
| `maintenance` | Dependency updates: Renovate's pull requests merge here. | Renovate's app and the maintainer, directly or through a pull request. | No |
| `develop` | Development in progress. | The maintainer, directly or through a pull request. | No |

Every pull request into any of the three runs the same checks ([`pipeline.md`](ci/pipeline.md)). Merges are merge commits on all three, so a promoted commit stays an ancestor of `main`.

## The rulesets

Repository rulesets (Settings > Rules) enforce this; none of it is in the repository. The rules, and who may bypass them:

| Ruleset | Applies to | Rules | Bypass |
| :--- | :--- | :--- | :--- |
| `main` | `main` | The 15 required checks ([`pipeline.md`](ci/pipeline.md#requiring-checks-before-merge)), no deletion, no force push. | Nobody |
| `main-review` | `main` | A pull request, merge commits only, and an `update` rule that refuses every change to anyone off the bypass list. | The Admin role, for pull requests only: a promotion can be merged, nothing can be pushed. |
| `maintenance-and-develop` | `maintenance`, `develop` | A pull request and the same 15 checks. | The Admin role and the Renovate app, always: a direct push is allowed. |
| `keep-branches` | `maintenance`, `develop` | No deletion, no force push. | Nobody, so it holds for the maintainer and the app too. |

Two facts shape the table. An approving review is not used on `main`: an approval from the Renovate app counts towards one, and a sole maintainer cannot approve their own pull request, so the `update` rule is what stops any credential but the maintainer merging. And the `keep-branches` rules sit in their own ruleset because a rule in a ruleset with a bypass list can be bypassed, and GitHub's "delete branch on merge" acts as the merging actor, so with a bypass it removes the branch a promotion came from. Rules with no bypass list cannot be bypassed, so the setting can stay on for every other branch.

To retire or rebuild one of the branches, turn `keep-branches` off first and back on afterwards.

## Dependency updates

The Renovate workflow runs daily ([`renovate.md`](ci/renovate.md)). Its first step makes `maintenance` contain `main` (a fast-forward, or a merge commit when the two have diverged), and Renovate then opens its pull requests into `maintenance`. Merge those you want; they do not deploy. When a batch is ready, promote `maintenance`.

If the realignment step fails, `main` and `maintenance` conflict and the run stops before Renovate starts. `maintenance` is unchanged. Merge `main` into it by hand, push, and dispatch the workflow again:

```sh
git fetch origin
git switch --detach origin/maintenance
git merge origin/main                  # resolve the conflicts and commit
git push origin HEAD:maintenance
```

## Promoting

1. Open a pull request from `maintenance` or `develop` into `main`. A workflow writes a **Run after merging** block into its description ([`pipeline.md`](ci/pipeline.md#promotion-checklist)); your own text around it is kept, and a box you tick stays ticked when the block is rewritten.
2. When the checks are green, merge it with **Create a merge commit**, using the bypass. Never squash: the squashed content reaches `main` and the commits do not, so the branch is no longer an ancestor of `main`.
3. The CD agent deploys within a few minutes. Run what the block lists that the agent does not apply, in its order. If it lists an OpenBao unseal, check `bao status` on `security` first and unseal only if it reports `Sealed true`.
4. The branch you promoted is now behind `main` by the merge commit. `maintenance` catches up at the next Renovate run. `develop` does not: realign it by hand.

The two branches promote independently, so a batch of updates does not wait for development, and the other branch is realigned afterwards.

## Realigning `develop`

`develop` is never rewritten, and it is realigned by hand because it holds work nothing else may touch. After anything lands on `main` (a promotion of either branch, or a fix):

```sh
git fetch origin
git switch develop && git pull --ff-only
git merge origin/main                  # a fast-forward when develop was just promoted; otherwise a merge commit
git push origin develop
```

A conflict is yours to resolve in that merge. Never `git rebase` or `reset` either branch onto `main`: Renovate treats a pull request as edited when another author's commits lie under it, and a rebase drops the promotion merge commits.

## A fix that cannot wait

Open the fix as its own pull request into `main` and merge it as above. Then `maintenance` follows at the next Renovate run, or sooner by dispatching the workflow, and you realign `develop`. A security update from Renovate either waits for the next promotion of `maintenance` or is made again as its own pull request into `main`.

## What does not run on the other branches

Scheduled workflows (the weekly Trivy and provenance scans, the tag and checksum checks, the progress log) run on the default branch only, so they look at `main`, which is what is deployed. A change on `maintenance` or `develop` meets the same checks on its pull request, and the weekly scans see it once it is promoted. No image is built or published from `maintenance` or `develop`: the build workflows' jobs run for `main` alone ([`gates.md`](ci/gates.md#dockerfile-changes)).
