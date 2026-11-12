# Pull Request Review

A pull request in this repo is reviewed when the maintainer asks for one. The review runs in `homelab-security`'s CI with a coding agent and its output is a private Issue there; this repo receives nothing from it. The decision is [ADR 0061 revision 1 (Automated code review)](../../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-001.md), and the rule that keeps output off this repo's surfaces is [`docs/README.md#public-repo`](../../README.md#public-repo).

## Requesting a review

Run it from a checkout of `homelab-security`, under your own `gh` login:

```bash
python -m agent_review.request review <pr>
```

`<pr>` is the number of a pull request in this repo. The command reads the pull request here, checks it against the private repo's limits and, if it passes, starts the review workflow there. `--dry-run` does the reading and the checking and starts nothing. The limits and the rest of the command are in the private repo's own docs, and this doc does not copy them.

A request is refused for a pull request that is a draft, one whose required checks are not all passing, one from a fork, a closed one and one that is too large, and the private repo limits how often a pull request, and the repo as a whole, is reviewed. The required checks are the ones this repo's branch ruleset names ([`branching.md`](branching.md#the-rulesets)), read at each request.

So keep a pull request a draft until it is ready, and ask for the review once its checks are green.

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
