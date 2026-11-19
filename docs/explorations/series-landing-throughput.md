---
id: EXP-series-landing-throughput
title: "Can a series land faster without giving up an exact check on every layer?"
type: exploration
status: open
summary: "Whether the CI waits of a series can overlap while each layer still merges serially as a clean pull request on the tree CI tested, and what a failure at each stage voids."
topic: repository-tooling
related: [ADR-0112, ADR-0114]
---

# Can a series land faster without giving up an exact check on every layer?

[`land_series`](../topics/engineering/landing-a-series.md) pushes a layer only after the one below it has merged, so a series of N layers waits for N CI runs in turn, the heavy ones (Molecule) included. A failure found in CI also sends the whole upper part of the series back through the replay. The serial order is what makes a layer's CI run test the tree that merges, so the question is whether the waits can overlap without losing that.

## What bears on it

- [ADR 0112 (Landing a patch series)](../decisions/0112-landing-a-series-of-dependent-changes-on-main/revision-001.md) lists opening layers in parallel as a non-goal and rejected deriving independence from a dependency graph: sharing no file does not show two layers independent. Its reconsideration triggers include CI waits long enough to justify fewer, larger layers. [ADR 0114 (Remote series landing)](../decisions/0114-landing-a-series-from-a-device-other-than-the-laptop/revision-000.md) repeats the non-goal, binds its approval to each layer's tree and gives its token only what merging needs.
- A check result belongs to a commit. The tool moves a layer onto the new tip with the same tree and a new commit id (`kept.rebase`), which keeps `main` on one line and is why a rebased layer has no CI result of its own.
- The `main` ruleset requires the 16 checks and has no bypass; `main-review` is the one the Admin role bypasses, for pull requests only ([`branching.md`](../topics/engineering/branching.md#the-rulesets)). The tool cannot vouch for a check that has not reported. The tool counts a skipped required job as passed.
- The jobs of [`pr-checks.yml`](../../.github/workflows/pr-checks.yml) scope themselves from `pull_request.base.sha` to `pull_request.head.sha`. They read no repository secret and run with the read-only `github.token`, apart from the scan that uploads its results. Fifteen workflows already take `workflow_dispatch`, among them Renovate and the image builds.
- The Python unit tests run only as the `python-unit-tests` job. No pre-commit or pre-push hook runs them, and the replay runs the project scope check and `pre-commit run --all-files`. The tool's `git push` runs the installed pre-push hooks, and pre-commit runs hooks against the working tree, so a pre-push hook would probably not test the commit pushed. The remote-landing console pushes with hooks off.
- The replay does not run the heavy jobs (Molecule, the compose boot test, the Dockerfile builds, the deploy-ordering check): the first three need Docker and the last needs the Ansible Galaxy collections, which an environment without registry access cannot fetch ([`checks-without-docker.md`](../topics/engineering/checks-without-docker.md)).
- A rebuilt layer is not always byte-identical to the first build: the planning view's table of explorations dates each by its newest commit, and a change not yet committed counts as today. A layer that adds or edits an exploration therefore differs between two replays.
- A review is asked for by hand on a pull request once its required checks pass, and `land_series` advises on it from each layer's own commits ([`pr-review.md`](../topics/engineering/pr-review.md)). A review is recorded against one pull request number, so a layer's proof and its real pull request are two different subjects.
- Of the 200 newest merged pull requests, 59 changed a generated view, so two layers that share no file can still conflict on one. Whether the views need to be committed at all is a question of its own.

## Options

- **Keep the order and shift checks left.** Run the unit tests at each pull request's tip in the replay, scoped by the same filter CI uses, so the cheapest CI failure is found before anything is pushed. Costs a tip-only check in the replay. It does not overlap any wait.
- **Reuse the layers below a fix.** Record each layer that passed and reuse its commit when its patch and the tree under it are unchanged, so a re-issued series skips what already passed. Saves replay time only, and a failed replay currently keeps nothing. Needed by the proof option below unless proofs are keyed another way.
- **Cumulative heads on `main`.** Push every layer at once as a pull request into `main` whose head holds the layers below it, and merge in order. Each run tests exactly what will merge. The graph becomes a ladder (the first-parent history and one-layer reverts are unchanged), a pull request shows its ancestors until they merge, the scope check judges the cumulative diff and refuses a layer that needs an earlier layer's widening, a layer's commits belong to two pull requests, a failure low in the series voids every run above it, and the window in which `main` can move spans the whole series. A required up-to-date rule would break it.
- **Merge file-disjoint layers in parallel.** The merged tree is a merge nobody tested, the generated views conflict, and it still needs the author to declare independence. Lost.
- **Batch through a staging branch and promote once.** One CI run and one deploy, but `main`'s first-parent history shows one promotion instead of a merge per layer, and the layers deploy together, which a layer with an operator step cannot. `develop` is a long-lived branch realigned by hand and promoting it would carry whatever else it holds. A new branch needs a ruleset made by hand, since rulesets are not in the repository.
- **Prove in parallel, land serially and clean.** Each layer's heavy checks run on a proof of it that is never merged: a stacked pull request whose base is the proof of the layer below, or a run of one workflow dispatched from `main` with the base and head as inputs. A proof's result is keyed on the pair of trees, base and head. The real pull requests land as today, one at a time and rebased, and a job that sees a green proof for the same tree pair lets the heavy jobs skip. If `main` has moved the trees differ and the heavy jobs run, which is today's behaviour. Costs:
  - The attestation is a trust boundary on a branch that deploys. It has to be code under `tools/ci` with unit tests, fail closed, require a run of the real workflow, and never apply to a diff that touches a workflow, an action or `tools/ci`.
  - A stacked proof needs no new permission, runs the full `pr-checks` unchanged and leaves N unmerged pull requests behind. A dispatched proof runs `main`'s copy of the workflow, so a layer cannot change what tests it, but it needs the heavy jobs extracted from `pr-checks.yml`, a token with `actions: write` (wider than the remote console's), and a run name to find the run by, since a dispatch returns no handle.
  - Every layer below a fix has to keep its tree. That needs the reuse above, or a key that leaves the generated views out of the tree, which no heavy job reads.
- **Gate the proofs above a layer only CI can test.** The scoping that already decides which jobs a diff queues (`ci.scope` and `detect-changes-filters.yml`) can mark a layer CI-only: it would run Molecule, the compose boot test or a Dockerfile build, or it changes a workflow, an action or `tools/ci`. Such a layer holds back the proofs above it until its own proof is green, so a failure there wastes none of them. A layer that queues no heavy job needs no proof. With every layer gated the series lands as it does now, and with none it is fully parallel, so the rule trades wall-clock time against runner time without changing what lands. It needs a way to opt a series out.
- **Queue several series as one chain.** A console that queues series ([ADR 0114 (Remote series landing)](../decisions/0114-landing-a-series-from-a-device-other-than-the-laptop/revision-000.md)) could replay the series behind on the expected tip of the one ahead, so its proofs run while the first still waits and lands, and treat the two as one longer series. A failure in the one ahead discards the replay of the one behind. It costs a replay on a tip that may not exist, and it touches the approval: ADR 0114 binds an approval and a token to one series, so a queued series either holds its approval while it waits, with the token's lifetime that implies, or asks for it when it reaches the head.

## What a failure voids under the last option

A fix to layer k changes the trees of layer k and every layer above it.

| Found at | Voided | Kept | Reruns |
| :--- | :--- | :--- | :--- |
| Claude's dry-run, or the local replay | nothing pushed | layers below k | the dry-run or replay from k; a full series is re-issued with the layers below k unchanged |
| A proof | proofs of k and above, cancelled if still running | proofs below k; those layers keep landing | replay from k, then new proofs for k and above in parallel |
| The serial landing | pull request k and above, and their proofs | layers below k, already merged | as above; the costliest, so everything the proof can catch should be caught before it |

A flaky job is rerun in place: the commit and trees are unchanged, so no replay follows. A merge to `main` that is not part of the series, or a declined review, is a fix at that layer. A failure after a merge is reverted as that layer's merge, or fixed forward.

## Leaning

The unit-test check at each tip and the reuse of unchanged layers are worth doing on their own. The proof option keeps the serial, clean landing the series has now and moves only the waiting, so it is the one to try, with stacked proofs first because they change no workflow. Gating the proofs above a CI-only layer and queuing series as one chain are refinements of it, to be added once the plain version holds. Cumulative heads are the fallback if it does not hold.

## What has to be checked first

- On a scratch repository with a ruleset shaped like `main`: whether a pull request stacked on another branch gets a `pull_request` run once the workflow lists that branch, whether a skipped required job satisfies the ruleset, and whether a run's result can be read back by tree pair.
- How long a CI run and the unit tests take, and whether N proofs at once reach the runners' concurrent-job limit.
- Whether any automation reads a pull request's diff, since a proof's diff is the layer's own but a cumulative head's is not.
- What the apply hooks see of the patch's date, which decides whether the generated views can be made identical between replays.
- Where a review of a layer would be asked for: on the real pull request at the merge prompt, as now, or earlier on its stacked proof, whose diff is the layer's own commits on the tree that will land. The second overlaps the review with CI. It depends on whether the review request accepts a pull request whose base is not `main` and which required checks it reads then, which only the review tooling's own docs say.
- Whether pre-commit's pre-push stage tests the working tree or the commit pushed, which decides if a pre-push hook for the unit tests is of any use to the tool's own push.
