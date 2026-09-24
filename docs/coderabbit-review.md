# CodeRabbit PR Review

Per-PR diff review with the [CodeRabbit](https://coderabbit.ai) CLI,
containerized under
[`tools/coderabbit-review/`](../tools/coderabbit-review/coderabbit-review.sh)
so nothing needs installing on the host. It reviews one thing: the diff
between the current branch and a base branch. The unattended caller is
`homelab-security`'s CI ([ADR 0061](decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md));
until that pipeline exists, the maintainer runs it by hand before a push.
Nothing in this repo's own workflows runs a review or uses GitHub's
CodeRabbit App — see [Why output stays off this repo's surfaces](#why-output-stays-off-this-repos-surfaces).

## Setup

Authenticate once. Interactively (opens a browser step; the login persists
under `~/.coderabbit`):

```bash
./tools/coderabbit-review/coderabbit-review.sh auth
```

Or headlessly, for CI, with an [Agentic API key](https://docs.coderabbit.ai/cli/headless-cli-integration)
from the CodeRabbit dashboard:

```bash
CODERABBIT_API_KEY=... ./tools/coderabbit-review/coderabbit-review.sh auth --api-key
```

The key is forwarded to the container by name (`docker run -e
CODERABBIT_API_KEY`), never as an argument, so it isn't in the script's or
the host's `docker` command line. The login lands in the same
`~/.coderabbit` a later `review` reads.

There is no build step. Every command runs
`ghcr.io/wenenhoe/coderabbit-review:latest`, which
[`build-coderabbit-review-image.yml`](../.github/workflows/build-coderabbit-review-image.yml)
rebuilds on a `Dockerfile` change and weekly, for base-OS patches. Docker pulls the image on first use;
`docker pull ghcr.io/wenenhoe/coderabbit-review:latest` refreshes a local
copy. The container runs as the invoking user (`docker run -u`), and the
script refuses to run as root.

## Image tags and the pinned CLI

The CLI is not installed with upstream's `install.sh`. The
[`Dockerfile`](../tools/coderabbit-review/Dockerfile) downloads one
release's `linux-x64` zip, checks it against a pinned sha256, and only then
unpacks it; a wrong hash fails the build. The version
(`CODERABBIT_VERSION`) and the hash (`CODERABBIT_SHA256`) are both
declared there ([ADR 0063](decisions/0063-what-the-code-review-image-is-built-from-and-how-it-stays-current/revision-000.md)).

Each build pushes two tags: `:<cli-version>` (for example `:0.8.0`) and
`:latest`. A pull request that changes the `Dockerfile` builds the image
without pushing it, so a wrong hash fails the PR and not `main`. The weekly
rebuild refreshes the base OS under the current
version's tag; the CLI itself changes only when the `Dockerfile` does. A
pinned CLI prints a notice when a newer release exists. That is expected,
and nothing applies it (see the
[non-goals](decisions/0063-what-the-code-review-image-is-built-from-and-how-it-stays-current/revision-000.md#non-goals)).

**Bumping the CLI.** Set `CODERABBIT_VERSION`, and replace
`CODERABBIT_SHA256` with the `coderabbit-linux-x64.zip` entry from that
release's manifest:

```bash
curl -fsSL https://cli.coderabbit.ai/releases/latest/VERSION
curl -fsSL https://cli.coderabbit.ai/releases/<version>/SHA256SUMS | grep -F ' ./coderabbit-linux-x64.zip'
```

The manifest comes from the same bucket as the zip, so the hash catches a
swapped artifact but does not prove a new release was good.

**Backing out.** Revert the bump; the rebuild republishes the previous CLI
as `:latest`. To back out on one machine at once, retag an older version
locally, since `docker run` uses a local image without pulling:

```bash
docker pull ghcr.io/wenenhoe/coderabbit-review:<older-version>
docker tag ghcr.io/wenenhoe/coderabbit-review:<older-version> ghcr.io/wenenhoe/coderabbit-review:latest
```

That holds until the next `docker pull` of `:latest`.

## Commands

The script works from anywhere inside the repo; it mounts the repo root
read-only, since a review only reads the tree to compute a diff.

| Command | Does |
| :--- | :--- |
| `review [base-branch] [cr flags]` | Reviews the current branch's diff against the base (default `main`). Extra flags go to `cr review`; `--agent` gives structured JSON for another tool to parse. |
| `auth` | Interactive login. |
| `auth --api-key` | Headless login from `CODERABBIT_API_KEY`; see [Setup](#setup). |
| `usage` | `cr usage` — billing-period review count/spend/reset date, not an hourly-remaining counter. |

## Why output stays off this repo's surfaces

This repo is public, so a review's findings must not appear on any surface
it controls before a human has seen them: a PR comment, a commit, or a
GitHub Actions run log. The GitHub App would post findings as PR comments
the moment a PR opens, and a review run from this repo's own workflows
would log them publicly. [ADR 0061](decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md)
therefore runs the review from `homelab-security`'s own CI and lets it
write only there ([ADR 0060](decisions/0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-000.md)),
and [`README.md`](README.md#public-repo) is the rule this protects. For
this tool that means the only workflow here builds the image, which holds
no findings, and a local run prints to your terminal and nowhere else.

## Credit

`Dockerfile` is adapted from rikatz's
[coderabbit-cli-docker gist](https://gist.github.com/rikatz/1135c311d86306a5bff3e39276968b17).
