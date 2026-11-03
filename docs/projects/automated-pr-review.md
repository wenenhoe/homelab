---
id: PROJ-automated-pr-review
title: "Automated pull request review"
type: project
status: not-started
blocked: false
summary: "Review a pull request from the private repository's CI when the maintainer labels it, describe the practice here, try it against the local CodeRabbit run, and accept the decision."
decision: ADR-0061/1
allowed_paths:
  - docs/topics/engineering/pr-review.md
  - docs/topics/engineering/coderabbit-review.md
  - docs/topics/README.md
---

# Automated pull request review

Carries out [ADR 0061 revision 1 (Automated code review)](../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-001.md):
a pull request is reviewed from the private repository's CI when the maintainer applies the `review` label,
and nothing about the review reaches this repository's surfaces. Most of the build is in the private
repository, so this doc tracks what lands here and the order in which the rest is shown to work.

## Scope

- The decision reaching `approved`, once its open assumptions are resolved.
- The review built and shown to work end to end in the private repository.
- A topic doc for the practice here: the `review` label, a pull request kept as a draft until its checks are
  green, and what the review does and does not do on this repository's surfaces. The local-run topic doc
  says it is no longer the only per-pull-request review.
- A trial on labelled pull requests, and the maintainer's decision about the local CodeRabbit run.
- Accepting the decision.

Not in scope: how the private repository chooses, limits or prompts its reviews; retiring the CodeRabbit
CLI, its image and the decisions about them, which is its own decision if the trial leads to it; any
workflow in this repository that triggers, or holds a secret for, the private one.

## Decision

[ADR 0061 revision 1 (Automated code review)](../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-001.md),
`working`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Resolve the assumptions and approve the decision | Not started | The private repository has read this repository's labels, label events and check results with its own token and written nothing here, and the first labelled reviews' use of the shared allowance is measured; both assumptions of the revision are resolved and it is `approved` |
| 2 | The review in the private repository | Not started | A labelled pull request in this repository is selected, reviewed and its output opened as a pull request in the private repository, with nothing added here beyond the label; a pull request without the label, a draft, one whose checks are red and one labelled by anyone else are each left alone |
| 3 | The practice described here | Not started | `pr-review.md` (a new topic doc) states the label, the draft and green-checks practice and what the review leaves on this repository's surfaces, has its row in [`topics/README.md`](../topics/README.md), and [`coderabbit-review.md`](../topics/engineering/coderabbit-review.md) says the local run is one of two |
| 4 | Trial | Not started | The review has run on labelled pull requests for several weeks, the shared allowance and the maintainer's reading pace held, and the maintainer has decided whether the local CodeRabbit run stays |
| 5 | Accept the decision | Not started | ADR 0061 revision 1 is `accepted`; this doc is deleted by its closing checklist |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] Labelling a pull request in this repository leads to a review in the private repository, and the label
  is the only trace of it here.
- [ ] No workflow in this repository triggers one in the private repository or holds a secret for it.
- [ ] A review is requested only by the maintainer; a label applied by anyone else is ignored.
- [ ] The topic doc describes the practice and what the review leaves on this repository's surfaces.
- [ ] The maintainer has decided what happens to the local CodeRabbit run.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** a workflow under `.github/workflows/` to trigger the private repository, to hold a secret
  for it or to post anything about a review; the decision's invariants.
- **Relevant files and interfaces:** [`coderabbit-review.md`](../topics/engineering/coderabbit-review.md) for the
  local run; the private repository's own rules, which this project does not restate.
- **Required checks:** `pre-commit run --all-files`.

## Risks

- The review and the audit draw on one subscription allowance, shared with interactive use
  ([ADR 0062 (Reviewer identity)](../decisions/0062-automation-identity-for-the-agent-based-reviewer/revision-000.md));
  the trial is what shows whether it holds.
- A pull request is reviewed up to a poll interval after it is labelled, and can merge first; the review is
  advice, not a gate.

## Open items

- Whether a check should fail a workflow in this repository that dispatches to another repository or holds a
  secret for one, since the decision's invariant is kept by review of the change alone.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
