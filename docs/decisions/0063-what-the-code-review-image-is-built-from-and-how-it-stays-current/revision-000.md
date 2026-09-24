---
id: ADR-0063
revision: 0
type: adr
title: "What the code-review image is built from, and how it stays current"
solution: "Pin the CLI's version and the release zip's sha256, verify the zip before unpacking it, bump the version with Renovate from the release's VERSION file, use an Ubuntu LTS base, and tag every image with its CLI version"
summary: "How the image that runs the CodeRabbit CLI is versioned, based, and kept up to date when upstream publishes no machine-readable release list."
topic: repository-tooling
status: working
related: [ADR-0061]
---

# 0063. What the code-review image is built from, and how it stays current

## Problem

The image that runs the CodeRabbit CLI for per-PR review must follow
new CLI releases and its base OS's security fixes without anyone
tracking them by hand, and any image must be traceable to the CLI
version inside it so a bad release can be backed out.

## Context

- **Upstream.** The CLI is distributed through `install.sh`. It downloads
  `releases/<version>/coderabbit-<os>-<arch>.zip` and checks it against a
  `SHA256SUMS` manifest from the same directory, where `<version>` is
  either `CODERABBIT_VERSION` or the contents of `releases/latest/VERSION`
  used verbatim. That file currently reads `0.8.0`, with no leading `v`,
  and `releases/0.8.0/SHA256SUMS` lists `coderabbit-linux-x64.zip`
  exactly once, as `<sha256>  ./coderabbit-linux-x64.zip`. The installer
  strips the `./` before matching, so a Dockerfile check has to as well.
  The manifest check detects corruption and warns rather than fails when
  the manifest is missing; it is not a signature, and the installer gives
  a caller no way to supply its own expected hash.
- **Renovate.** No built-in datasource covers this CLI. Renovate can read
  a plain-text endpoint through `customDatasources` with
  `format: plain`, and `latest/VERSION` is the only version endpoint
  found. The repo already pins native CLIs through a custom regex
  manager (`openbao_cli` in `renovate.json5`).
- **Today.** The image installs whatever "latest" is at build time and is
  rebuilt weekly. Neither the Dockerfile nor the image records a
  version, so a build can't be reviewed, compared, or rolled back. Its
  base, `fedora:43`, reaches end of life in late 2026; Fedora releases are
  supported for about 13 months.
- **Consumers.** `coderabbit-review.sh` and, later, `homelab-security`'s
  CI run the image ([ADR 0061](../0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md)).
  The molecule image and the CI runners are Ubuntu 26.04 LTS, and the
  official `ubuntu:26.04` image exists.

**Threat model.** The adversary is a tampered CLI artifact at the
vendor's release bucket. The asset is the API key the container is handed
at runtime. The path is a build that installs whatever the bucket serves
that day. A recorded hash closes it for any version whose artifact is
replaced after the hash was recorded, and makes every artifact change a
diff to review. It does not help if the artifact is already bad when a
bump records its hash, since the new hash comes from the same bucket.

## Decision

- **Pin the CLI and its hash.** The Dockerfile declares
  `ARG CODERABBIT_VERSION` and `ARG CODERABBIT_SHA256`, the latter the
  `linux-x64` zip's entry in that release's `SHA256SUMS`. The build
  downloads the zip from the release directory the installer uses, fails
  unless it matches the hash, and only then unpacks it. It doesn't run
  `install.sh`. The final image needs only `git` and the binary, not the
  download tooling. No build installs an unversioned or unverified CLI.
- **Bump the version with Renovate.** A custom datasource reads
  `releases/latest/VERSION` as one release, and a regex manager updates
  the version `ARG`. Renovate can't compute the hash, so its PR body
  carries a reminder, as for `openbao_cli`, to replace it from that
  release's `SHA256SUMS`. A version or hash change is built before it
  merges, so a wrong hash fails in the PR, not on `main`. Bump PRs are
  reviewed by hand, like other Dockerfile updates.
- **Ubuntu LTS base.** `FROM ubuntu:26.04`, tracked by Renovate's
  Dockerfile manager, so a new LTS arrives as its own PR. Packages come
  from `apt` unpinned, on the same reasoning as the existing hadolint
  ignore for the molecule image.
- **Tag by version.** Each build pushes `:<cli-version>` and `:latest`.
  Backing out means pointing a consumer at an older `:<cli-version>`.
  The weekly rebuild stays, now for base-OS patches, so a version tag's
  OS layer may be refreshed while its CLI version and hash never change.

## Alternatives considered

- **Stay unpinned and rebuild weekly.** Nothing to review, no version to
  name, no rollback. Rejected.
- **Keep running `install.sh` with `CODERABBIT_VERSION`.** It fetches its
  own copy and checks it only against the same bucket's manifest, so a
  pinned hash can't be applied to what it installs. Rejected in favor of
  downloading the release zip directly. That ties the build to the
  installer's URL layout, which only the installer itself documents; a
  change there fails the build loudly rather than installing something wrong.
- **Let the CLI update itself at runtime** (`coderabbit update`). Changes
  a running container after the fact and defeats reproducibility.
  Rejected.
- **Stay on Fedora.** Its short lifecycle forces a base bump about every
  year and it matches nothing else in the repo. Rejected.
- **Debian slim.** Equivalent for this purpose; Ubuntu wins on matching
  the molecule image and CI runners. Rejected.
- **Alpine.** No evidence the binary runs on musl. Not pursued.

## Assumptions

- **Claim:** The CLI runs on `ubuntu:26.04`, whose default coreutils are
  uutils rather than GNU's.
  **Breaks if wrong:** The base choice, and with it the image.
  **Checked by:** building the image and running `auth --api-key` and a
  real review in it.
- **Claim:** A CLI pinned a few days behind `latest` still works against
  the service.
  **Breaks if wrong:** Reviews fail between a release and its bump
  merging.
  **Checked by:** CodeRabbit's documentation on version support, or a
  review run with an older pinned version.
- **Claim:** Renovate's `format: plain` custom datasource turns the
  `VERSION` body into a single release.
  **Breaks if wrong:** No bump PRs are ever opened.
  **Checked by:** a Renovate dry run against the real endpoint.

## Consequences

- The Dockerfile is rewritten on the new base, `renovate.json5` gains a
  custom datasource and manager, and the publish workflow computes the
  tags. [`docs/coderabbit-review.md`](../../coderabbit-review.md)
  describes the tags and how to back out.
- Every CLI release becomes a PR to review. In exchange the image names
  its CLI version and a bad release can be reverted.
- Every bump needs a hand step, copying the new hash from the release's
  `SHA256SUMS`. That is the price of the pin, and the reason the PR
  carries a reminder.
- Bypassing `install.sh` means the build depends on its URL layout and
  archive contents (a `coderabbit` binary at the archive root).
- Resolves the open question of whether the image needs a tag beyond
  `:latest`.

## Invariants

- The Dockerfile names the CLI version it installs and the sha256 the
  download must match.
- Every published image carries a tag naming its CLI version.

## Non-goals

- Proving the artifact was good when a bump recorded its hash; that
  would need upstream signatures.
- Multi-arch images; `linux/amd64` only, as today.
- Pinning individual `apt` packages.

## Validation

`hadolint` on the Dockerfile, a build of every version or hash change
before it merges, the publish workflow's own run, and a Renovate dry run
showing the datasource yields a bump. After a base or
CLI change, `auth --api-key` and a review against the published image.

## Reconsideration triggers

- Upstream signs its Linux release artifacts: verify the signature, on
  top of or instead of the hash.
- The hand step per bump becomes a burden: automate it or reconsider.
- Upstream publishes GitHub releases or another machine-readable release
  list: replace the custom datasource.
- Ubuntu LTS 26.04 nears the end of its support: Renovate's PR for the
  next LTS is the prompt; nothing to decide here.
