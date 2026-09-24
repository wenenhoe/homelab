---
id: PROJ-coderabbit-image-pinning
title: "CodeRabbit Image: Pinned CLI, Ubuntu Base"
type: project
status: de-risking
blocked: false
summary: "Pin the CodeRabbit CLI in the review image, bump it with Renovate, move the base to Ubuntu LTS, and tag images by CLI version."
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
- The Dockerfile on `ubuntu:26.04` with a pinned `CODERABBIT_VERSION`.
- The publish workflow pushes `:<cli-version>` and `:latest`.
- A Renovate custom datasource and manager for the pinned version.
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
| 1 | Spike: resolve the ADR's four assumptions with throwaway work only | Not started | Each assumption is resolved into the ADR's Context, or the Decision changes; ADR 0063 is `approved` |
| 2 | Dockerfile on `ubuntu:26.04` with the pinned CLI; workflow tags by version | Not started | `hadolint` clean; the published image runs `auth --api-key` and a review of a real diff |
| 3 | Renovate custom datasource and manager; update `docs/coderabbit-review.md` | Not started | A Renovate dry run proposes a bump from the real endpoint; the doc describes the tags and rollback |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] The Dockerfile names the CLI version it installs and builds `FROM`
      `ubuntu:26.04`.
- [ ] Every published image carries a `:<cli-version>` tag as well as
      `:latest`.
- [ ] Renovate opens a bump PR when upstream's `VERSION` changes.
- [ ] `docs/coderabbit-review.md` describes the tags and how to back out.
- [ ] ADR 0063 is `accepted`.

## Agent handoff

Stop conditions are in [`README.md#stop-conditions`](README.md#stop-conditions);
they apply without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** how `coderabbit-review.sh` authenticates or runs
  the container, and the workflow's triggers.
- **Relevant files and interfaces:** `tools/coderabbit-review/Dockerfile`,
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
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
