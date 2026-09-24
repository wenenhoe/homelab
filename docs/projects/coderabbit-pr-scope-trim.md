---
id: PROJ-coderabbit-pr-scope-trim
title: "CodeRabbit: Trim to PR-Diff Review"
type: project
status: building
blocked: false
summary: "Rescope tools/coderabbit-review/ to per-PR diff review only; move image building into CI."
decision: ADR-0061/0
super_project: security-review-pipeline
allowed_paths:
  - tools/coderabbit-review/**
  - docs/coderabbit-review.md
  - .github/workflows/build-coderabbit-review-image.yml
---

# CodeRabbit: Trim to PR-Diff Review

`tools/coderabbit-review/` was built for a full local repo sweep — an
architecture superseded by
[ADR 0061](../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md):
CodeRabbit now covers only per-PR diffs, and the full-repo audit moves to
an agent
([`agent-full-repo-audit`](agent-full-repo-audit.md)). This project
trims the tool to match, and stops the operator's own machine (or a
private-repo CI job) from building the review image locally at all.

## Scope

- Drop `full-review`, `status`, `report`, and `reset` — the resumable,
  whole-repo-sweep machinery, including `require_safe_output_dir`,
  `output_dir`, and `state_file`, which exist only to serve those
  commands. (This removes code added in two earlier patches to this
  branch — correct at the time, dead once the commands they guarded are
  gone.)
- Add a headless `--api-key` authentication path alongside the existing
  interactive `auth login`, for `homelab-security`'s CI to use.
- Drop `cmd_build` and the operator-invoked `docker build` step
  entirely. Add `.github/workflows/build-coderabbit-review-image.yml` in
  this repo, following `build-molecule-dind-image.yml`'s precedent (a
  mutable `:latest` tag, since — like that image — this one has no
  meaningful upstream version to tag by): triggered on a push touching
  `tools/coderabbit-review/Dockerfile`, a weekly schedule (catches a
  newer CodeRabbit CLI release landing without the Dockerfile's own text
  changing — the primary reason a schedule matters here, since the
  install script deliberately always fetches "latest"), and
  `workflow_dispatch`. Pushes to `ghcr.io/wenenhoe/coderabbit-review`.
  `auth`/`review` pull that image instead of building `coderabbit-cli`
  locally.
- Rewrite `docs/coderabbit-review.md` for the new scope: PR-diff review,
  invoked from `homelab-security`'s CI or locally before a push. "Why
  local-only" becomes "why output never surfaces on this repo's own
  surfaces," pointing at ADR 0061 rather than re-deriving the reasoning.

Not in scope: `homelab-security`'s own CI workflow that calls this tool
([`coderabbit-pr-review-pipeline`](coderabbit-pr-review-pipeline.md));
the agent audit
([`agent-full-repo-audit`](agent-full-repo-audit.md)).

## Decision

Implements [ADR 0061](../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md),
`approved`.

## Execution plan

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Remove `full-review`/`status`/`report`/`reset` and their now-unused support functions | Done | `shellcheck` clean; `auth`/`review`/`build` still work unchanged |
| 2 | Add `--api-key` headless auth alongside interactive `auth login` | Done | A `review` call authenticates non-interactively given an API key |
| 3 | Add `build-coderabbit-review-image.yml`; drop `cmd_build`; point `auth`/`review` at the pulled image | In progress | Workflow builds and pushes on a path-filtered change or the weekly schedule; the script runs against the pulled image with no local `docker build` |
| 4 | Rewrite `docs/coderabbit-review.md` for the new scope | Done | `pre-commit run --all-files` and `check-doc-drift.py` pass |

## Acceptance criteria

- [x] `full-review`, `status`, `report`, `reset` are removed.
- [x] The `--api-key` path authenticates a review with no browser step.
- [ ] The image builds and publishes via CI only; nothing in the script invokes `docker build`.
- [x] `docs/coderabbit-review.md` describes only the PR-diff scope and cites ADR 0061.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, above.
- **Must not change:** any other `docker/*/Dockerfile` or `build-*-image.yml` workflow.
- **Relevant files and interfaces:** `.github/workflows/build-molecule-dind-image.yml` (the `:latest`-tag, no-upstream-version precedent this follows); `build-caddy-image.yml` / `build-wastebin-image.yml` (the paths-filter-plus-schedule idiom, shown for contrast — their version-tag strategy doesn't apply here).
- **Required checks:** `pre-commit run --all-files`; `shellcheck`/`hadolint` (already covered by the repo's existing hooks, no new config needed).

## Risks

- The pulled image runs under `docker run -u <invoking uid>:<gid>`, a UID
  it has no passwd entry for. `HOME` is pinned to the world-writable
  (sticky) `/home/coderabbit` so the `$AUTH_DIR` mount and the CLI's other
  writes have somewhere to land. Whether the CLI and `git` both behave
  under an unmapped UID hasn't been run yet; stage 3 stays In progress
  until a live `auth` and `review` against the published image confirm it.

## Open items

- Whether the published GHCR package is readable by `homelab-security`'s CI, or needs a public package or a read token; check after the first push.
- Whether the published image needs any tag beyond `:latest` for rollback purposes, or floating is acceptable given the CLI itself is unpinned by design regardless.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
