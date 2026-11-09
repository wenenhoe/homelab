---
id: EXP-refactoring-review-lens
title: "Can the automated review look for refactoring without producing noise?"
type: exploration
status: open
summary: "Whether a review concerned with structure (duplication, drift from the repo's own conventions, code that no longer earns its place) can be held to evidence and a cap, where its output goes, and how its findings turn into work."
topic: repository-tooling
related: [ADR-0060, ADR-0061]
---

# Can the automated review look for refactoring without producing noise?

The automated review reads the repo for defects. A question about structure is a different kind of question: a defect has a failure that can be shown, while "this would be better arranged" is a judgment, and a review asked for judgments tends to return many of them. Whether a structural review is worth running depends on whether it can be held to findings the maintainer would act on.

## What bears on it

- The review's output stays off this repo's surfaces and is filed in the private tracker ([ADR 0060 (Review findings tracker)](../decisions/0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-001.md), [ADR 0061 (Automated code review)](../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-001.md)). That rule is about the review's surface, not about what a finding says, so a structural review inherits it. A different lane for findings that are not sensitive would be a new revision of ADR 0061, not a property of the review.
- The tracker's finding schema and triage states were written for defects. Whether a structural finding fits them, or needs its own, has to be checked against the private repo's schema.
- The repo already states what a structural review can test against: the comment rules in `AGENTS.md`, [`conventions.md`](../topics/engineering/conventions.md), and the doc rules in [`docs/README.md`](../README.md) (one home for a fact, current names, no stage vocabulary in code). Several are held by a check already; a review finding that a check could catch is a missing check, not a finding.
- A refactor is only safe where behaviour is guarded. Molecule scenarios with the idempotence check guard the roles; the Python unit tests guard `tools/`; mutation testing covers only the credential tooling ([`mutation-testing.md`](../topics/engineering/mutation-testing.md)). Elsewhere a restructure has nothing to say it kept the behaviour.
- Another review draws on the same subscription allowance as the audit and the per-pull-request review ([ADR 0062 (Reviewer identity)](../decisions/0062-automation-identity-for-the-agent-based-reviewer/revision-000.md)), and measuring that allowance is a stage of [the automated review project](../projects/automated-pr-review.md).
- A restructure that spans files is project work: it needs a stage, an exit condition and an `allowed_paths`. A one-file tidy is an ordinary change.

## Options

- **Fold it into the existing reviews as one more instruction.** No new run and no new allowance. Structural findings then mix with defects at one severity scale, and the ones that matter least crowd the ones that matter most.
- **A separate review with rules on what it may report.** Each finding names a cost that can be read off the repo: the same logic in several places, a rule from the sources above that the code breaks, files that always change together in the history, a path nothing refers to. Findings are capped per run and ranked by the cost of leaving the code as it is. A finding may not propose undoing an accepted decision, and one in code nothing guards says so. Costs a run of its own and a place in the tracker's schema.
- **Turn the checkable part into repo checks and keep the review for judgment only.** A finding that recurs becomes a check that runs on every pull request at no allowance. Each check is code to keep, so only a pattern that has recurred earns one.
- **Do not review for structure.** Refactoring then happens when the maintainer notices it. Cheapest, and it leaves the drift the other options exist to find.

## Leaning

A separate review under the evidence rules, run less often than the defect reviews, with a recurring finding moved into a check. A first run on a bounded part of the repo would show what share of its findings the maintainer would act on; if most are not actionable, the evidence rules are too loose or the idea is dropped.
