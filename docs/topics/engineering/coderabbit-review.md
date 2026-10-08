# CodeRabbit PR Review

Per-PR diff review with the [CodeRabbit](https://coderabbit.ai) CLI,
containerized under
[`tools/coderabbit-review/`](../../../tools/coderabbit-review/coderabbit-review.sh)
so nothing needs installing on the host. It reviews one thing: the diff
between the current branch and a base branch. The maintainer runs it by
hand before a push. It is not run from CI: unattended use needs a headless
Agentic API key, which the plan in use does not issue
([ADR 0061 (Automated code review)](../../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md#alternatives-considered)).
Nothing in this repo's own workflows runs a review or uses GitHub's
CodeRabbit App — see [Why output stays off this repo's surfaces](#why-output-stays-off-this-repos-surfaces).

## Setup

Authenticate once, interactively (it opens a browser step; the login
persists under `~/.coderabbit`):

```bash
./tools/coderabbit-review/coderabbit-review.sh auth
```

There is no build step. Every command runs
`ghcr.io/wenenhoe/coderabbit-review:latest`, which
[`build-coderabbit-review-image.yml`](../../../.github/workflows/build-coderabbit-review-image.yml)
rebuilds on a `Dockerfile` change and weekly, for base-OS patches. Docker pulls the image on first use;
`docker pull ghcr.io/wenenhoe/coderabbit-review:latest` refreshes a local
copy. The container runs as the invoking user (`docker run -u`), and the
script refuses to run as root.

## Image tags and the pinned CLI

The CLI is not installed with upstream's `install.sh`. The
[`Dockerfile`](../../../tools/coderabbit-review/Dockerfile) downloads one
release's `linux-x64` zip, checks it against a pinned sha256, and only then
unpacks it; a wrong hash fails the build. The version
(`CODERABBIT_VERSION`) and the hash (`CODERABBIT_SHA256`) are both
declared there ([ADR 0063 (Review image build)](../../decisions/0063-what-the-code-review-image-is-built-from-and-how-it-stays-current/revision-000.md)).

Each build pushes two tags: `:<cli-version>` and
`:latest`. A pull request that changes the `Dockerfile` builds the image
without pushing it and smoke-tests it, in the same `dockerfile-build-check`
as the other images ([Dockerfile changes](ci/gates.md#dockerfile-changes)),
so a wrong hash fails the PR and not `main`. The weekly
rebuild refreshes the base OS under the current
version's tag; the CLI itself changes only when the `Dockerfile` does. A
pinned CLI prints a notice when a newer release exists. That is expected,
and nothing applies it (see the
[non-goals](../../decisions/0063-what-the-code-review-image-is-built-from-and-how-it-stays-current/revision-000.md#non-goals)).

**Bumping the CLI.** Renovate opens a PR when
`https://cli.coderabbit.ai/releases/latest/VERSION` changes, on the repo's
usual schedule ([`renovate.json5`](../../../.github/renovate.json5)). It changes
`CODERABBIT_VERSION` only, so the PR's build check fails at the checksum
step until `CODERABBIT_SHA256` is replaced with the `coderabbit-linux-x64.zip`
entry from that release's manifest; the PR body says so. Push that change to
the PR's branch. To bump by hand, set both. The manifest and the current
version:

```bash
curl -fsSL https://cli.coderabbit.ai/releases/latest/VERSION
curl -fsSL https://cli.coderabbit.ai/releases/<version>/SHA256SUMS | grep -F ' ./coderabbit-linux-x64.zip'
```

The manifest comes from the same bucket as the zip, so the hash catches a
swapped artifact but does not prove a new release was good. Nothing signs or
attests this CLI's Linux releases (no signature file sits beside the
manifest or the zip), so the
[release checksum check](ci/release-checksum-check.md) can only confirm
that the pinned hash is the one the manifest lists: it catches a hash copied
wrongly, not a bucket that served a bad artifact.

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
| `usage` | `cr usage` — billing-period review count/spend/reset date, not an hourly-remaining counter. |

## When to run it

Before pushing a branch that changes code or config, with the work
committed. Run the script from inside this repo: it reviews the repository
it is run in, so running it from another checkout reviews that one by
mistake. The output stays in your terminal. Don't redirect it into this
repo's working tree, where a `git add` could publish it.

## Why output stays off this repo's surfaces

This repo is public, so a review's findings must not appear on any surface
it controls before a human has seen them: a PR comment, a commit, or a
GitHub Actions run log. The GitHub App would post findings as PR comments
the moment a PR opens, and a review run from this repo's own workflows
would log them publicly. [ADR 0061 (Automated code review)](../../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md)
therefore keeps automated review out of this repo's workflows, and
[`README.md`](../../README.md#public-repo) is the rule this protects. For
this tool that means the only workflow here builds the image, which holds
no findings, and a local run prints to your terminal and nowhere else.
A result worth tracking goes to the private tracker by a pipe, never a
saved file ([`security-findings.md`](security-findings.md)).

## Credit

`Dockerfile` is adapted from rikatz's
[coderabbit-cli-docker gist](https://gist.github.com/rikatz/1135c311d86306a5bff3e39276968b17).
