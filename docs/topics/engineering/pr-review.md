# Pull Request Review

A pull request in this repo is reviewed when the maintainer asks for one. The review runs in `homelab-security`'s CI with a coding agent and its output is a private Issue there; this repo receives nothing from it. The decision is [ADR 0061 revision 1 (Automated code review)](../../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-001.md), and the rule that keeps output off this repo's surfaces is [`docs/README.md#public-repo`](../../README.md#public-repo).

## Requesting a review

Run it from a checkout of `homelab-security`, under your own `gh` login:

```bash
python -m agent_review.request review <pr>
```

`<pr>` is the number of a pull request in this repo. The command reads the pull request here, checks it against the private repo's limits and, if it passes, starts the review workflow there. `--dry-run` does the reading and the checking and starts nothing. The limits and the rest of the command are in the private repo's own docs, and this doc does not copy them.

A request waits for a pull request that is a draft or whose required checks are not all passing, and is refused for one from a fork, a closed one and one that is too large; the private repo also limits how often a pull request, and the repo as a whole, is reviewed. The required checks are the ones this repo's branch ruleset names ([`branching.md`](branching.md#the-rulesets)), read at each request.

So keep a pull request a draft until it is ready, and ask for the review once its checks are green.

## When it is worth asking

[`tools/review_criteria`](../../../tools/review_criteria/criteria.py) decides from the diff alone whether a change is worth a review, so the answer does not depend on anyone's judgment of the day. [`land_series`](landing-a-series.md#advice-on-a-review) prints it for each pull request it replays, and again before it asks to merge one. Run it by hand from `tools/` with `python -m review_criteria BASE HEAD --repo ..`. It is advice and blocks nothing.

Any one major criterion recommends a review. The two minor ones recommend it only together.

| Id | Kind | A change that touches |
| :--- | :--- | :--- |
| R1 | major | Automation, or a tool that holds credentials or deploys: `.github/`, `.githooks/`, `pyproject.toml`, `uv.lock`, and `cd_agent`, `land_series`, `openbao_utils` and `cloud_credentials` under `tools/`, tests apart. |
| R2 | major | Secrets handling: the `secrets`, `openbao`, `openbao_cli`, `step_ca_cert`, `step_ca_client`, `tinyauth` and `tinyauth_ca_trust` roles, the `openbao`, `step-ca` and `tinyauth` service directories, and the secret catalog. |
| R3 | major | What is reachable: a new route in the app catalog, a published port in a compose file, or the check that governs open routes. |
| R4 | major | The check that holds container hardening, which is where a service's excuses are listed. |
| R5 | major | Backup, restore or off-site sync: the `backup_agent`, `restore`, `restore_discovery` and `cloud_sync` roles, or a `backup` block in the app catalog. |
| R6 | major | Production OpenTofu: the `.tf` and `.tfvars` files at the top of `tofu/` and under `tofu/modules/`, not `tofu/scratch/` or tests. |
| r1 | minor | Code (`.py`, `.sh`, `.tf`) changed with no test changed. |
| r2 | minor | A large change: 800 or more changed lines, or 30 or more files, not counting documents and the lock file. |

A path criterion counts a changed line only if it is not blank and not a comment, and never counts a markdown file, so a change to documents alone recommends nothing. What a script already decides, such as an unpinned image, a dangling file reference or an edit to an accepted decision, is not a criterion. The two minor thresholds are generous on purpose and are meant to be tuned.

## Where the output lives

In one Issue for each pull request in `homelab-security`, created by the first review of a pull request and edited by later ones. Nothing is posted, committed, labelled or logged in this repo, and no workflow here starts a review or holds a secret for the private repo.

Two more commands, run the same way, tidy the Issues:

| Command | Does |
| :--- | :--- |
| `python -m agent_review.request status` | Lists the open review Issues. |
| `python -m agent_review.request sync` | Closes the Issue of a pull request that has merged or closed. `--dry-run` shows which. |

Neither runs by itself.

## What it is not

It is not a check on the pull request and cannot block a merge, and it does not run unless it is asked for: a pull request nobody requests is never reviewed. How this repo may refer to what a review produced is in [`security-findings.md`](security-findings.md).
