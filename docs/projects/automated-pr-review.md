---
id: PROJ-automated-pr-review
title: "Automated pull request review"
type: project
status: building
blocked: false
summary: "Review a pull request from the private repository's CI when the maintainer requests it from there, describe the practice here, and accept the decision."
decision: ADR-0061/1
allowed_paths:
  - docs/topics/engineering/pr-review.md
  - docs/topics/engineering/coderabbit-review.md
  - docs/topics/README.md
---

# Automated pull request review

Carries out [ADR 0061 revision 1 (Automated code review)](../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-001.md):
a pull request is reviewed from the private repository's CI when the maintainer requests it from the private
checkout, and nothing about the review reaches this repository's surfaces. Most of the build is in the private
repository, so this doc tracks what lands here and the order in which the rest is shown to work.

## Scope

- The decision reaching `approved`, once its open assumptions are resolved.
- The review built and shown to work end to end in the private repository.
- A topic doc for the practice here: how a review is requested by hand, a pull request kept as a draft until
  its checks are green, and what the review does and does not do on this repository's surfaces.
- A trial on requested pull requests.
- Accepting the decision.

Not in scope: how the private repository chooses, limits or prompts its reviews; retiring the CodeRabbit
CLI, its image and the decisions about them, which is its own decision; any workflow in this repository that
triggers, or holds a secret for, the private one.

## Decision

[ADR 0061 revision 1 (Automated code review)](../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-001.md),
`working`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Approve the decision | Done | The assumptions of the revision are resolved and it is `approved` |
| 2 | The review in the private repository | Not started | A pull request in this repository, requested from the private checkout, is reviewed and its output filed as an Issue in the private repository, with nothing added here; a draft, one whose required checks are not green, a fork's, a closed one and one that is too large are each refused |
| 3 | The practice described here | Not started | `pr-review.md` (a new topic doc) states how a review is requested, the draft and green-checks practice, where the output lives and what the review leaves on this repository's surfaces, and has its row in [`topics/README.md`](../topics/README.md) |
| 4 | Trial | Not started | Reviews have been requested on pull requests for several weeks, and the shared allowance and the maintainer's reading pace held |
| 5 | Accept the decision | Not started | ADR 0061 revision 1 is `accepted`; this doc is deleted by its closing checklist |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] Requesting a review of a pull request from the private checkout leads to a review in the private
  repository, and nothing is added here.
- [ ] No workflow in this repository triggers one in the private repository or holds a secret for it.
- [ ] A review is requested only by the maintainer; nothing on this repository's surfaces can request one.
- [ ] The topic doc describes the practice and what the review leaves on this repository's surfaces.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** a workflow under `.github/workflows/` to trigger the private repository, to hold a secret
  for it or to post anything about a review; the decision's invariants.
- **Relevant files and interfaces:** the private repository's own rules, which this project does not restate.
- **Required checks:** `pre-commit run --all-files`.

## Risks

- The review and the audit draw on one subscription allowance, shared with interactive use
  ([ADR 0062 (Reviewer identity)](../decisions/0062-automation-identity-for-the-agent-based-reviewer/revision-000.md));
  the trial is what shows whether it holds.
- A pull request can merge before its review finishes; the review is advice, not a gate.

## Open items

- Whether a check should fail a workflow in this repository that dispatches to another repository or holds a
  secret for one, since the decision's invariant is kept by review of the change alone.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
