---
id: PROJ-pinned-release-checksum-verification
title: "Pinned Release Checksum Verification"
type: project
status: building
blocked: false
summary: A CI check that each pinned release sha256 is the one its publisher signed or lists, for uv, rclone, the OpenBao CLI and the CodeRabbit CLI.
decision: ADR-0077/0
allowed_paths:
  - tools/ci/checksums/**
  - tools/tests/ci/checksums/**
  - tools/tests/ci/test_stdlib_only.py
  - .github/workflows/pr-checks.yml
  - .github/workflows/check-release-checksums.yml
  - ansible/roles/openbao_cli/defaults/main.yaml
  - docs/topics/engineering/ci/**
  - docs/topics/engineering/coderabbit-review.md
---

# Pinned Release Checksum Verification

Carries out [ADR 0077](../decisions/0077-knowing-a-pinned-release-checksum-is-the-publishers/revision-000.md): the hash pinned for each downloaded release is shown to be the publisher's, whoever copied it in. It is staged because conditions in that revision had to be shown first, and what the check can promise per artifact depended on them; the check is built now that they are.

## Scope

In: closing the revision's open assumptions with throwaway spikes (done), the registry and verifier under `tools/ci/checksums/` with unit tests, the committed public keys, the pull request and weekly CI runs, and the comments and docs that state the current "not independently verified" stance.

Not in: verifying at deploy time, any `gpg` or publisher address on a host, container image signatures, and how Renovate supplies a hash ([`.github/renovate.json5`](../../.github/renovate.json5) is not changed here).

## Decision

Implements [ADR 0077](../decisions/0077-knowing-a-pinned-release-checksum-is-the-publishers/revision-000.md), revision 0.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Close the open assumptions with throwaway spikes: OpenBao's signature, uv's attestation, and a run from a GitHub-hosted runner | Done | Each assumption's entry is deleted from the revision, its fact folded into Context or the Decision changed, with nothing from the spikes committed |
| 2 | The revision is approved | Done | The revision is `approved`, with no open assumption |
| 3 | The registry, the verifier and the committed keys, unit-tested | Not started | The unit tests in the revision's Validation pass, including the one asserting every checksum pin has a registry entry |
| 4 | The check runs on a pull request that changes a pin or the registry, and weekly | Not started | Both runs pass against the real publishers, and a pin changed to a wrong hash fails the pull request run |
| 5 | The docs and comments state each pin's tier | Not started | No file says a signed artifact is unverified, and a topic doc names the tiers and where the registry is |

Stage status is `Not started`, `In progress`, or `Done`.

Stages 1 and 2 are done, and the project is `building`.

## Acceptance criteria

- [ ] A signed artifact whose signature is missing, invalid or by another key fails the check, verified by unit tests with a generated key.
- [ ] An attested artifact fails when `gh attestation verify` exits non-zero, including a run against the wrong repository, verified by a test double and once against the real tarball.
- [ ] A pinned hash that is absent from its manifest, or differs from the manifest's line, fails the check, verified by unit tests.
- [ ] Every checksum pin in the repository has a registry entry with a tier, verified by a test.
- [ ] No key is fetched when the check runs, verified by a test that denies network access to the key step.
- [ ] The weekly run reaches each publisher's manifest and passes on the current pins.
- [ ] No host role gains `gpg` or a publisher address.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the revision's Decision except as stage 1 and the stop conditions in [`README.md#stop-conditions`](README.md#stop-conditions) permit; the install-time `checksum:` and `sha256sum -c` controls.
- **Relevant files and interfaces:** the four pins are `cd_agent_uv_sha256` and `cd_agent_rclone_sha256` in `ansible/roles/cd_agent/defaults/main.yaml`, `openbao_cli_deb_sha256` in `ansible/roles/openbao_cli/defaults/main.yaml`, and `CODERABBIT_SHA256` in `tools/coderabbit-review/Dockerfile`. The code lives where [ADR 0064](../decisions/0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md) puts CI code, stdlib-only.
- **Required checks:** `pre-commit run --all-files`; `uv run pytest tools/tests/ -v`.

## Risks

- A runner image with a newer GnuPG may refuse rclone's 1024-bit DSA key; it passed under 2.4.4 and 2.4.8.
- A uv release without an attestation fails its bump pull request.
- A publisher's key rotation fails the weekly run until the new key is reviewed and committed.
- The check depends on each publisher's manifest address staying where it is.
- A new `.github/workflows` file or path filter has to keep the required-check aggregator `matrix-jobs-gate` accurate.

## Open items

- Whether a `listed` artifact's failure message should print the manifest's line for the pinned file, so the CodeRabbit pin, which Renovate cannot move, is fixed by copying it.
- Whether the OpenBao, uv or CodeRabbit publishers offer an attestation that would make their pin `signed` ([ADR 0077](../decisions/0077-knowing-a-pinned-release-checksum-is-the-publishers/revision-000.md), alternatives considered).

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or named by a successor project.
- [ ] The linked revision is `accepted`, another project still names it, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
