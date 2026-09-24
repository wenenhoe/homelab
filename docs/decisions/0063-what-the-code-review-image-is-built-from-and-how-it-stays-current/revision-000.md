---
id: ADR-0063
revision: 0
type: adr
title: "What the code-review image is built from, and how it stays current"
solution: "Pin the CLI through the installer's own version variable, bump it with Renovate from the release's VERSION file, use an Ubuntu LTS base, and tag every image with its CLI version"
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

- **Upstream.** The CLI is distributed through `install.sh`. Its header
  documents `CODERABBIT_VERSION` to pin a version; it then downloads
  `releases/<version>/coderabbit-<os>-<arch>.zip` and checks it against a
  `SHA256SUMS` manifest from the same directory. Unpinned, it resolves
  `releases/latest/VERSION`. The manifest check detects corruption and
  warns rather than fails when the manifest is missing; it is not a
  signature.
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
that day.

## Decision

- **Pin the CLI.** The Dockerfile declares `ARG CODERABBIT_VERSION` and
  passes it to the installer as `CODERABBIT_VERSION`. No build installs an
  unversioned CLI.
- **Bump it with Renovate.** A custom datasource reads
  `releases/latest/VERSION` as one release, and a regex manager updates
  the `ARG`. Bump PRs are reviewed by hand, like other Dockerfile
  updates.
- **Ubuntu LTS base.** `FROM ubuntu:26.04`, tracked by Renovate's
  Dockerfile manager, so a new LTS arrives as its own PR. Packages come
  from `apt` unpinned, on the same reasoning as the existing hadolint
  ignore for the molecule image.
- **Tag by version.** Each build pushes `:<cli-version>` and `:latest`.
  Backing out means pointing a consumer at an older `:<cli-version>`.
  The weekly rebuild stays, now for base-OS patches, so a version tag's
  OS layer may be refreshed while its CLI version never changes.

## Alternatives considered

- **Stay unpinned and rebuild weekly.** Nothing to review, no version to
  name, no rollback. Rejected.
- **Also pin the zip's sha256**, as `openbao_cli` does. It is the only
  option here that defends against a swapped artifact under an unchanged
  version, which the installer's own check cannot. Renovate can't compute
  the hash, so every bump needs a manual step. Not adopted for now; see
  Reconsideration triggers.
- **Let the CLI update itself at runtime** (`coderabbit update`). Changes
  a running container after the fact and defeats reproducibility.
  Rejected.
- **Stay on Fedora.** Its short lifecycle forces a base bump about every
  year and it matches nothing else in the repo. Rejected.
- **Debian slim.** Equivalent for this purpose; Ubuntu wins on matching
  the molecule image and CI runners. Rejected.
- **Alpine.** No evidence the binary runs on musl. Not pursued.

## Assumptions

- **Claim:** The contents of `releases/latest/VERSION` are accepted as-is
  by the installer's `CODERABBIT_VERSION`, including whether a leading
  `v` is part of the value.
  **Breaks if wrong:** Renovate proposes values the installer can't
  download, or the pin and the directory name disagree.
  **Checked by:** fetching the file and running a pinned install with
  exactly that string.
- **Claim:** The installer and CLI run on `ubuntu:26.04`, whose default
  coreutils are uutils rather than GNU's.
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
- Without a hash pin, a replaced artifact under the same version would be
  installed and would then see the API key. Version pinning makes each
  change reviewable and reproducible; it doesn't prove authenticity.
- Resolves the open question of whether the image needs a tag beyond
  `:latest`.

## Invariants

- The Dockerfile names the CLI version it installs.
- Every published image carries a tag naming its CLI version.

## Non-goals

- Authenticity of the CLI binary beyond the installer's manifest check.
- Multi-arch images; `linux/amd64` only, as today.
- Pinning individual `apt` packages.

## Validation

`hadolint` on the Dockerfile, the publish workflow's own run, and a
Renovate dry run showing the datasource yields a bump. After a base or
CLI change, `auth --api-key` and a review against the published image.

## Reconsideration triggers

- The API key gains a wider reach than reviewing this repo, or a vendor
  artifact incident is reported: adopt the sha256 pin.
- Upstream publishes GitHub releases or another machine-readable release
  list: replace the custom datasource.
- Ubuntu LTS 26.04 nears the end of its support: Renovate's PR for the
  next LTS is the prompt; nothing to decide here.
