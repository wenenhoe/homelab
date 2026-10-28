---
id: ADR-0096
revision: 0
type: adr
title: Knowing the pre-commit hooks that run are the ones that were reviewed
short: Pre-commit hook pins
solution: Each hook repository is pinned to a full commit SHA with its tag in a comment, each docker hook's image is pinned by digest in the config, and Renovate moves both in a reviewed pull request
summary: How the pre-commit hook code and the images hooks pull are made to be the ones a commit names, so they change only in a pull request that shows the change.
topic: security-hardening
status: working
related: [ADR-0064, ADR-0077, ADR-0083, ADR-0084]
---

# 0096. Knowing the pre-commit hooks that run are the ones that were reviewed

## Problem

The pre-commit config names each hook repository by a tag. A tag is a name its publisher can point at other code whenever it likes, so two runs of the same commit can run different hook code. The hooks run in CI with the pull request's full history and a read token, and the jobs that warm the hook-environment cache write what they built, including the `gitleaks` binary the range scan reuses, into a cache every later job restores. A hook that changed under an unchanged tag therefore runs in CI and leaves its build behind for the jobs after it.

[ADR 0083 (Images a deploy runs)](../0083-making-a-deploy-run-the-images-its-commit-names/revision-000.md) pins every image the repository runs in CI by digest, and GitHub Actions are pinned by commit SHA. The hook repositories, and the images some of their hooks pull, are the part of CI's inputs that neither covers.

What has to be true: the hook code and hook images that run at a commit are the ones the commit names, and they change only in a pull request that shows the change.

## Context

- **What is pinned today.** Eleven hook repositories, each by `rev:` set to a release tag. The `ansible-lint` override and the local hooks install their Python dependencies at exact versions.
- **Three hooks run a container image**, and the image is named by the hook repository's own manifest at the pinned revision, not by the config. Read from those manifests: `dclint-docker` runs `zavoloklom/dclint` at a tag, `actionlint-docker` runs `docker.io/rhysd/actionlint` at a tag, and `hadolint-docker` runs `ghcr.io/hadolint/hadolint` with no tag at all, so the pinned `rev:` does not decide which hadolint runs.
- **pre-commit accepts a commit SHA as `rev:`.** It clones the repository at that commit and records it under the SHA. `ci.scan.gitleaks_range` reads the `gitleaks` rev from the config as written, so a SHA there reaches the cache lookup unchanged.
- **How Renovate reads a pinned hook.** Run locally at the pinned Renovate version against a test config, its `pre-commit` manager reads `rev: <sha> # v6.0.0` as a dependency whose version is the SHA and ignores the comment, so it has no tag to compare against. Whether it can then keep such a pin current was not observed: the sandbox could not reach the GitHub API the lookup needs. The same run read exact-version `additional_dependencies` on a hook that states `language: python` and found newer releases on PyPI.
- **A precedent for tag and SHA moving together.** `tools/ci/shell_tests/pins.txt` holds a repository, release tag and commit SHA on one line, and a Renovate regex manager on the `github-tags` datasource moves them as a pair, with `ci.shell_tests.pins` checking the pairing. Its comment records that where the datasource cannot supply a new tag's SHA the bump is made by hand.
- **What a SHA shows.** It fixes the content that runs. It does not show the content is what the hook's publisher meant to release; that is the question [ADR 0077 (Pinned checksum verification)](../0077-knowing-a-pinned-release-checksum-is-the-publishers/revision-000.md) and [ADR 0084 (Image digest provenance)](../0084-knowing-a-pinned-image-digest-is-the-publishers/revision-000.md) answer for their own inputs.

**Threat model.** The adversary can move a tag in a hook repository, or in the namespace a hook's image comes from, and cannot make a commit SHA name different content. The assets are what CI can reach (a read token, the pull request's history) and the shared cache that later jobs restore. The attack path is a hook run on an unchanged commit that pulls the moved tag. Pinning removes that path for an unattended run; the one that remains is a pull request that moves a pin to the adversary's revision, which is reviewed like any other bump.

## Decision

- **Hook repositories.** Every `rev:` is a full 40-character commit SHA with the release tag in a trailing comment (`rev: <sha> # v6.0.0`).
- **Hook images.** The config overrides the `entry` of each `docker_image` hook with the image pinned as `name:tag@sha256:digest` followed by the command the manifest ran, so the config decides which image runs. The tag stays for people and for Renovate's version comparison.
- **Renovate maintains both.** A custom regex manager on the `github-tags` datasource reads each `repo:`/`rev:` pair, takes the tag from the comment as the version and the SHA as the digest, and writes both back. The built-in `pre-commit` manager's handling of hook repositories is turned off, because it would read the SHA as a version; its handling of `additional_dependencies` stays. The image entries are tracked as the other images are in [ADR 0083](../0083-making-a-deploy-run-the-images-its-commit-names/revision-000.md), by a manager that reads and writes the digest. Pull requests keep the existing `pre-commit hooks` group and are not automerged.
- **A check keeps the pins honest.** A stdlib-only check under `tools/ci`, unit-tested ([ADR 0064 (CI and doc check code)](../0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md)), fails a hook repository whose `rev:` is not a full SHA with a tag comment, a `docker_image` hook whose entry names an image without a digest, and an `additional_dependencies` entry without an exact version. The image digests also go through the existing image pin and provenance checks, whose scope grows to the pre-commit config.

## Alternatives considered

- **Keep tags and run `pre-commit autoupdate --freeze` by hand.** Pins the repositories on the day it is run and leaves nothing to keep them current or to catch an unpinned hook added later.
- **Rely on Renovate's built-in `pre-commit` manager to pin and bump SHAs.** It reads the SHA as the version and ignores the tag comment, so it has nothing to follow; what it would do on a lookup was not observed.
- **Pin only the repositories and leave the images to the manifests.** Leaves `hadolint-docker` free to run any image published under its name, and the other two on tags.
- **Replace the docker hooks with local hooks installed from a pinned release.** Removes the manifest's say over the image, at the cost of an install step per hook that the three hooks' publishers already provide as an image.
- **Mirror the hook repositories.** A repository to run and keep current, to defend against a risk a SHA already covers.

## Assumptions

- **Claim:** The `github-tags` datasource supplies the commit SHA of every new tag in the eleven hook repositories, annotated tags included.
  **Breaks if wrong:** A pin goes stale, or a bump pull request carries a tag with no SHA and is made by hand, as the Bats pins already allow for.
  **Checked by:** A Renovate dry run with a GitHub token against the proposed config, listing the update it would make for each hook repository.
- **Claim:** pre-commit runs a `docker_image` hook whose `entry` is overridden to a digest-pinned image followed by the manifest's command, and each of the three images behaves the same under it.
  **Breaks if wrong:** The three hooks fail or change what they check, and the images stay on tags.
  **Checked by:** A spike on a host with Docker running the three hooks over the repository before and after the override.

## Consequences

- The first pull request touches every `rev:` and the three image entries, and later ones arrive grouped, as they do now.
- An image override decouples the image from the hook repository's revision. `actionlint`'s own comment that one bump moves both stops holding, and a bump of the hook repository no longer brings its image with it.
- The hook-environment cache key is the config file's hash, so the change rebuilds the cache once.
- [`pre-commit.md`](../../topics/engineering/pre-commit.md) and [`renovate.md`](../../topics/engineering/ci/renovate.md) describe the resulting behaviour once it is built.

## Invariants

- No hook repository is named by a tag alone, no `docker_image` hook runs an image without a digest, and no `additional_dependencies` entry lacks an exact version.
- A pin changes only in a pull request.

## Non-goals

- Showing that a pinned commit or image is the one its publisher released. Where a publisher offers a signature or attestation, [ADR 0084](../0084-knowing-a-pinned-image-digest-is-the-publishers/revision-000.md) already decides how that is checked for images.

## Validation

The check in Decision runs in `pre-commit-checks` on every pull request, and the Renovate dry run and the Docker spike above are what take the revision from `working` to `approved`.

## Reconsideration triggers

- Renovate's `pre-commit` manager learns to follow a tag comment on a SHA pin, which would remove the custom manager.
- A hook publisher starts signing its releases, which would let the SHA be checked against a statement as images are.
