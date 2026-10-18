---
id: PROJ-image-digest-provenance
title: "Image Digest Provenance"
type: project
status: building
blocked: false
summary: "Check each pinned image digest against its publisher's signature or attestation, and have the repository's own image builds attest what they push."
decision: ADR-0084/0
allowed_paths:
  - tools/ci/provenance/**
  - tools/tests/ci/provenance/**
  - tools/tests/ci/test_stdlib_only.py
  - tools/tests/ci/test_workflow_timeouts.py
  - docker/caddy/compose.yaml
  - docker/wastebin/compose.yaml
  - ansible/roles/*/molecule/*/molecule.yml
  - tools/ci/images/digests.py
  - docs/topics/engineering/molecule-fixtures.md
  - docs/topics/engineering/molecule-testing.md
  - tools/coderabbit-review/coderabbit-review.sh
  - docs/topics/engineering/coderabbit-review.md
  - .github/workflows/pr-checks.yml
  - .github/workflows/check-image-provenance.yml
  - .github/workflows/build-*-image.yml
  - .github/detect-changes-filters.yml
  - .github/renovate.json5
  - docs/topics/engineering/ci/**
  - docs/topics/README.md
  - README.md
  - SECURITY.md
---

# Image Digest Provenance

Adds a CI check that each digest the repository pins for a container image is one its publisher signed or attested, and makes the repository's own image builds attest the digests they push. It is staged because the checker, its registry of images, the CI wiring and the build-workflow change each ship and verify on their own, and the repository's own images can only be entered as *attested* once a build has produced an attested digest and the pins have followed it.

## Scope

In: a stdlib-only `tools/ci/provenance` package with unit tests; one registry entry per pinned image repository, in the *attested*, *signed* or *unsigned* tier; the cosign container image, pinned by digest and tracked by Renovate; a pull-request job and a weekly workflow; `id-token: write`, `attestations: write` and an `actions/attest` step in each `build-*-image.yml`; the topic doc and the pages that index the check.

Not in: which registry an image comes from ([ADR 0085](../decisions/0085-choosing-the-registry-an-image-is-pulled-from/revision-000.md)); release binaries and their checksums ([`release-checksum-check.md`](../topics/engineering/ci/release-checksum-check.md)); anything a host does at deploy time, since no host gains `gh`, `cosign` or a signer's address; reading an SBOM or provenance document; a `sourceUrl` rule or any other change to `.github/renovate.json5` beyond the image-pin managers for the cosign image, the Molecule platform image and the review script's image, and the rule that keeps the floating base out of the pins.

## Decision

Implements [ADR 0084 (Image digest provenance)](../decisions/0084-knowing-a-pinned-image-digest-is-the-publishers/revision-000.md), `approved`; this doc tracks build status only. [ADR 0085](../decisions/0085-choosing-the-registry-an-image-is-pulled-from/revision-000.md) settles which registry each image uses and needs no work here.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The checker | Done | `python3 -m ci.provenance.verify` reads a registry, takes every pinned digest of each listed image repository from the tree, and verifies it by its tier: `gh attestation verify` for *attested*, `cosign verify` with the entry's certificate identity and issuer or its committed public key for *signed*, nothing for *unsigned*. Unit tests with `gh` and `cosign` doubled cover a failing exit, an identity other than the entry's, a repository other than the entry's, an entry with no identity, and a negative control run against the wrong repository that must fail. `test_stdlib_only.py` lists the new modules |
| 2 | Registry entries for the pinned images | Done | Every image repository the tree pins has exactly one entry, and a test fails when one is missing or an entry matches nothing. Each third-party entry's tier and identity are the ones ADR 0084 records. The repository's own `ghcr.io/wenenhoe/*` images are *unsigned* with a reason that says they are not attested yet |
| 3 | Run it in CI | Done | The cosign version 3 container image is pinned by digest in the checker, tracked by a Renovate manager and covered by the image tag check. A `provenance` job in `pr-checks.yml` runs on a change to a pinned image reference or the registry, and `check-image-provenance.yml` runs weekly and on demand. Both use the runner's `gh` with the read-only token, and a failing entry fails the run. `docs/topics/engineering/ci/image-provenance-check.md` describes it, and the CI pages and the README and SECURITY control lists link it |
| 4 | Self-built images are attested | In progress | Each of the four `build-*-image.yml` workflows attests the digest it pushes with `actions/attest`, pinned to a commit SHA, with `id-token: write` and `attestations: write` on the build job and nothing wider, and a workflow test asserts those permissions. After merge, a build of each image produces a digest that `gh attestation verify -R wenenhoe/homelab` passes |
| 5 | Own images become *attested* entries | In progress | Each `ghcr.io/wenenhoe/*` compose pin and Molecule image reference is an attested digest, each entry is *attested* naming this repository, and the check passes on the pull request that flips the last of them |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 4 and 5 notes

Today's pins for the repository's own images were built before any attestation existed, so flipping an entry to *attested* before its pin moves would fail the check. Stage 4 therefore ships with the entries still *unsigned*; the weekly build schedule and any push to a Dockerfile produce the first attested digest, the pin follows it as an ordinary digest-refresh change, and stage 5 flips that image's entry. One image at a time is fine; stage 5 closes when the last one has flipped.

## Acceptance criteria

- [ ] Every image repository the tree pins has a registry entry, and the entry's tier matches what its publisher offers.
- [ ] A *signed* or *attested* entry fails the check when its statement is missing, invalid, or from another identity or repository, shown by a test for each and by a negative control.
- [ ] No identity, key or repository is read from the registry or the image being checked; each comes from the entry in the tree.
- [ ] The check runs on a pull request that changes a pinned image reference or the registry, and weekly, and a failure fails the run.
- [ ] The cosign image the check runs is pinned by digest, and no workflow installs a binary.
- [ ] Each `build-*-image.yml` attests the digest it pushes, and each `ghcr.io/wenenhoe/*` image passes `gh attestation verify -R wenenhoe/homelab` at the digest its compose pin names.
- [ ] No host gains `gh`, `cosign` or a call to a signer.
- [ ] `pre-commit run --all-files` passes.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** any ADR revision beyond the edits [`docs/decisions/README.md#assumptions`](../decisions/README.md#assumptions) permits; the Decision of ADR 0084; compose files, Dockerfiles and Ansible variables that name an image, other than a digest-refresh change to a self-built image's pin in stage 5; hosts and deploy playbooks.
- **Relevant files and interfaces:** `tools/ci/checksums/` (`registry.py`, `verify.py`) as the pattern for a registry plus verifier that fixes the signer in the tree and calls `gh attestation verify`; `tools/ci/images/remote.py` for how every pinned image reference is collected from compose files, Dockerfiles, Ansible and the Renovate custom managers; `tools/doc_scripts/check_mermaid.py`'s `MERMAID_CLI_IMAGE` and its manager in `.github/renovate.json5` as the pattern for an image named in a Python constant; `release-checksums` in `pr-checks.yml` and `check-release-checksums.yml` for the job and the weekly workflow; `docs/topics/engineering/ci/release-checksum-check.md` for the topic doc.
- **Required checks:** `pre-commit run --all-files`; `uv run pytest` from `tools/`; the new modules in `test_stdlib_only.py`; `ci.images.remote` against the new cosign pin for stage 3.

## Risks

- A signature or attestation that the registry shows is as good as the publisher's identity. Smallstep's is a reusable workflow at `refs/heads/main`, so the *signed* entry for its two images accepts any commit to that branch; the entry records what the publisher offers and no more.
- A publisher that moves or rotates its signing identity fails the weekly run until a human reviews the entry. That is the intended behaviour, and it will recur.
- cosign 2 finds no signature on the OpenBao and curl images that cosign 3 verifies, so the pinned cosign image must stay at version 3 or later; a Renovate bump that crossed back would fail those entries.
- The weekly run depends on GitHub's attestations API and on three registries answering. A registry that never answers fails the run after the checker's retries, so a weekly run can fail with nothing wrong in the tree; [`image-provenance-check.md`](../topics/engineering/ci/image-provenance-check.md) says how calls are retried.
- The four build workflows hold a package-write token and gain `id-token: write`; nothing else in them may widen.

## Open items

- **An image published to both registries with different statements.** ADR 0085's reconsideration trigger covers a publisher that signs differently per registry. If the registry needs one entry per reference rather than per repository for such an image, that is a change to ADR 0084 to propose, not to improvise.
- **`11notes/kms`.** Its workflow requests an attestation and GitHub holds none for the pinned digest, so it is *unsigned* today. If the publisher begins to attest, the entry changes tier in its own change.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
