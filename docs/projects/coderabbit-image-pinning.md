---
id: PROJ-coderabbit-image-pinning
title: "CodeRabbit Image: Pinned CLI, Ubuntu Base"
type: project
status: building
blocked: false
summary: "Pin and hash-verify the CodeRabbit CLI in the review image, bump it with Renovate, move the base to Ubuntu LTS, and tag images by CLI version."
decision: ADR-0063/0
super_project: security-review-pipeline
allowed_paths:
  - tools/coderabbit-review/**
  - .github/workflows/build-coderabbit-review-image.yml
  - .github/renovate.json5
  - docs/coderabbit-review.md
---

# CodeRabbit Image: Pinned CLI, Ubuntu Base

Implements
[ADR 0063](../decisions/0063-what-the-code-review-image-is-built-from-and-how-it-stays-current/revision-000.md).
The image is rebuilt weekly from an unversioned installer today; this
project makes its CLI version explicit, its updates reviewable, and its
base a release with a long support window. It starts as a spike because
the ADR still has open assumptions about the upstream version endpoint
and the new base.

## Scope

- A throwaway spike that resolves the ADR's assumptions.
- The Dockerfile on `ubuntu:26.04`, downloading the pinned CLI zip and verifying its pinned sha256 before unpacking it (no `install.sh`).
- The publish workflow pushes `:<cli-version>` and `:latest`.
- A Renovate custom datasource and manager for the pinned version, with a PR-body reminder to update the hash.
- `docs/coderabbit-review.md` describes the tags and how to back out.
- Not changed: the script's commands, the auth flow, or which workflow
  triggers the build.

## Decision

[ADR 0063](../decisions/0063-what-the-code-review-image-is-built-from-and-how-it-stays-current/revision-000.md).
Rationale lives there.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike: resolve the ADR's four assumptions with throwaway work only | Done | Each assumption is resolved into the ADR's Context, or the Decision changes; ADR 0063 is `approved` |
| 2 | Dockerfile on `ubuntu:26.04` with the pinned, hash-verified CLI; workflow tags by version and builds a version or hash change before it merges | Done | `hadolint` clean; a wrong hash fails the PR build; the published image runs `auth --api-key` and a review of a real diff |
| 3 | Renovate custom datasource and manager, with the hash reminder; update `docs/coderabbit-review.md` | In progress | A Renovate dry run proposes a bump from the real endpoint; the doc describes the tags, the hash step, and rollback |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [x] The Dockerfile names the CLI version it installs, verifies the zip
      against a pinned sha256 before unpacking it, and builds `FROM`
      `ubuntu:26.04`.
- [x] Every published image carries a `:<cli-version>` tag as well as
      `:latest`.
- [ ] Renovate opens a bump PR when upstream's `VERSION` changes, and the
      PR body reminds the reviewer to update the hash.
- [x] `docs/coderabbit-review.md` describes the tags, the hash step on a
      bump, and how to back out.
- [ ] ADR 0063 is `accepted`.

## Agent handoff

Stop conditions are in [`README.md#stop-conditions`](README.md#stop-conditions);
they apply without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** how `coderabbit-review.sh` authenticates or runs
  the container, and the publish workflow's `push`, `schedule` and
  `workflow_dispatch` triggers. Stage 2 may add one `pull_request` trigger
  that only builds: no registry login, no push, and no write permission.
- **Relevant files and interfaces:** `tools/coderabbit-review/Dockerfile`,
  `tools/coderabbit-review/resolve-version.sh`,
  `build-coderabbit-review-image.yml`, `renovate.json5`'s custom
  managers (`openbao_cli` is the closest existing example).
- **Required checks:** `hadolint`, `yamllint`, `pre-commit run
  --all-files`, and a live `auth --api-key` plus a review after stage 2.

## Risks

None open.

## Open items

None.

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
