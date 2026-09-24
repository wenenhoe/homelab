---
id: PROJ-security-findings-repo
title: "Security Findings Repository"
type: project
status: not-started
blocked: false
summary: "Create homelab-security, the private repo that tracks code-review findings for this public repo."
decision: ADR-0060/0
super_project: security-review-pipeline
---

# Security Findings Repository

Stands up `homelab-security`, the private repository
[ADR 0060](../decisions/0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-000.md)
names as where code-review findings for this repo live. Every other
project in this initiative writes into it; none of them can start until
it exists.

## Scope

Creating the private repository, its label scheme, and an issue template
for a finding (severity, file, description, source commit SHA, which
reviewer produced it). Deciding whether raw `report.jsonl`-style
artifacts get committed into the repo or kept as workflow artifacts
only. Not in scope: any code from this repo (ADR 0060 rules out a
mirror), and the CI workflows that populate it — those belong to
[`coderabbit-pr-review-pipeline`](coderabbit-pr-review-pipeline.md) and
[`agent-full-repo-audit`](agent-full-repo-audit.md).

## Decision

Implements [ADR 0060](../decisions/0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-000.md),
`approved`.

## Execution plan

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Create the private repository, with a README that states its purpose and links back to ADR 0060 | Not started | Repo exists, private, visible only to its owner |
| 2 | Label scheme and issue template for a finding | Not started | A finding can be filed by hand, matching the template, as a smoke test |
| 3 | Decide the archival convention for raw report artifacts (committed vs. workflow-artifact-only) | Not started | Documented in the repo's own README; referenced by the two CI projects below |

## Acceptance criteria

- [ ] `homelab-security` exists and is private.
- [ ] The label scheme and issue template are documented in its README.
- [ ] A hand-filed test issue matches the template.

## Agent handoff

- **Allowed to change:** nothing in this repo — this project's deliverable is the private repository itself, not a change here.
- **Must not change:** this repo's own files; no code from this repo is copied into `homelab-security`.
- **Relevant files and interfaces:** [ADR 0060](../decisions/0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-000.md).
- **Required checks:** none in this repo's CI, since nothing here changes.

## Risks

- None live-vulnerability-shaped; ordinary execution risk of a new repo's initial setup.

## Open items

- Exact label taxonomy (severity tiers, reviewer provenance).
- Raw artifact archival convention (stage 3, above).

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
