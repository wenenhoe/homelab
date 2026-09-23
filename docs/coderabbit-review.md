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
| `auth --api-key` | Headless login for CI: reads an [Agentic API key](https://docs.coderabbit.ai/cli/headless-cli-integration) from `CODERABBIT_API_KEY`, no browser step. The key is forwarded by name (`docker run -e CODERABBIT_API_KEY`), never as an argument. |
| `usage` | `cr usage` — billing-period review count/spend/reset date, not an hourly-remaining counter. |

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

## Credit

`Dockerfile` is adapted from rikatz's
[coderabbit-cli-docker gist](https://gist.github.com/rikatz/1135c311d86306a5bff3e39276968b17).
