# CodeRabbit CLI Review

Local, ad hoc code review via the [CodeRabbit](https://coderabbit.ai) CLI,
containerized under
[`tools/coderabbit-review/`](../tools/coderabbit-review/coderabbit-review.sh)
so nothing needs installing on the host. Not wired into
[`pr-checks.yml`](ci.md) or GitHub's CodeRabbit App — see
[Why local-only](#why-local-only).

## Setup

```bash
cd tools/coderabbit-review
./coderabbit-review.sh build   # once, or after an install.sh update upstream
./coderabbit-review.sh auth    # once; persists under ~/.coderabbit
```

## Commands

| Command | Does |
| :--- | :--- |
| `review [base-branch]` | One ad hoc review against the given base (default `main`). |
| `full-review [max-reviews]` | Walks the whole repo, one directory per call, security-sensitive paths first. Capped per invocation (default 3) to fit the plan's hourly rolling allowance; resumable. |
| `status` | Progress: how many directories are reviewed, how many remain. |
| `report` | Compiles every saved review into one findings file, sorted by severity. |
| `usage` | `cr usage` — billing-period review count/spend/reset date, not an hourly-remaining counter. |
| `reset` | Clears `full-review` progress. |

## Why local-only

This repo is public. The GitHub App posts findings as public PR comments
the moment a PR opens — unmerged doesn't mean unseen, and a PR that fixes
an already-deployed weakness is a public description of that weakness
until the fix merges (see [`README.md`](README.md#public-repo)). Path-
scoped exclusions that would keep security-sensitive directories
(`ansible/roles/**`, `docker/**/compose.yaml`) out of automatic PR review
while still letting the App comment elsewhere haven't been configured
yet, so the App stays off entirely for now and review happens locally
instead, where a finding is seen and can be fixed before anything about
it is public.

## One directory per review call

`full-review` issues one `cr review --dir <path>` call per directory,
never several `--dir` flags in one call. Multiple `--dir` flags were
tried first, on the reading that CodeRabbit's own over-limit error offers
up to five as a single narrowed retry — but they don't accumulate in
practice: the last one silently wins, so a batched call reviews only its
final directory while looking like it covered all of them. A path is
only recorded as reviewed after its files are confirmed present in that
call's own `reviewedFiles` result, rather than trusted from the request —
trusting the request is what let batched, unreviewed directories get
marked complete with a misleadingly reassuring zero-findings result.

## Credit

`Dockerfile` is adapted from rikatz's
[coderabbit-cli-docker gist](https://gist.github.com/rikatz/1135c311d86306a5bff3e39276968b17).
