---
id: PROJ-tofu-plan-guard
title: "Tofu plan guard"
type: project
status: not-started
blocked: false
summary: "Build the guard that checks a saved Tofu plan against a committed allow-list of destructive actions, the wrapper that applies the checked plan, and the pull request check that fails an address removed without one, then accept the decision."
decision: ADR-0102/0
allowed_paths:
  - tools/tofu_guard/**
  - tools/tests/tofu_guard/**
  - tofu/plan-intent.yaml
  - tools/ci/promotion/rules.py
  - tools/tests/ci/promotion/test_rules.py
  - .github/workflows/pr-checks.yml
  - docs/topics/engineering/ci/pipeline.md
  - docs/topics/infra/tofu-change-guard.md
  - docs/topics/README.md
---

# Tofu plan guard

Puts the review of a Tofu change into practice as [ADR 0102 (Tofu change review)](../decisions/0102-knowing-what-a-tofu-change-will-do/revision-000.md)
decides. It is staged because the guard is useful alone, the wrapper needs the guard, and the pull request check needs
the allow-list format the guard fixes. Each stage is one pull request.

## Scope

- A `tools/tofu_guard/` package: the plan-JSON parser, rules G1 to G6, the allow-list loader and the summary renderer.
- The wrapper that plans a ref, runs the guard, copies the state and applies the saved plan, and the promotion rule's
  command text.
- The `tofu-intent` job on pull requests, its address comparison, and the allow-list file it reads.
- A topic doc for the behaviour, written with the first stage and extended by the others.

Not in scope: a plan job on the CD agent, a remote state backend and write-scoped infrastructure credentials on any
host other than the operator host. Each is its own decision.

## Decision

[ADR 0102 (Tofu change review)](../decisions/0102-knowing-what-a-tofu-change-will-do/revision-000.md), `working`.
This project waits until the revision is `approved`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The guard | Not started | `tools/tofu_guard/` reads a plan's JSON and the allow-list and returns the verdict of rules G1 to G6, with unit tests on canned plan JSON and a control for each rule that fails without it; the topic doc describes the rules and the allow-list |
| 2 | The wrapper | Not started | A command plans a ref in a clean worktree and prints the summary, and another plans, guards, copies the state and applies the saved plan only on `ok`; tested with a stubbed `tofu`, including that the file applied is the one checked; the promotion rule for the Tofu directory names the guarded command and its test follows |
| 3 | The pull request check | Not started | A `tofu-intent` job compares addresses at the base and the head, reads `moved` blocks, and fails when an address of a protected type disappears without an entry; it reports `skipped` when nothing in the Tofu directory changed, and is a required check (the ruleset change is made by hand and named in the pull request) |
| 4 | Accept the decision | Not started | The guard is used for a real apply, ADR 0102 is `accepted`, and this doc is deleted by its closing checklist |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] A saved plan with a delete or replace of a protected resource and no entry returns a non-zero verdict, and the
      wrapper does not apply it.
- [ ] The wrapper applies the plan file the guard checked and no other.
- [ ] A pull request that removes a protected address without an entry fails `tofu-intent`, and one that moves it with a
      `moved` block does not.
- [ ] `tofu-intent` is a required check.
- [ ] ADR 0102 is `accepted`.

## Agent handoff

Stop conditions are in [`README.md#stop-conditions`](README.md#stop-conditions); they apply without being restated here.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the credential file or any infrastructure credential; Tofu configuration other than
  `plan-intent.yaml`; any decision revision other than ADR 0102's own.
- **Relevant files and interfaces:** `tools/ci/promotion/rules.py` (the Tofu rule), the `tofu-checks` job in
  `.github/workflows/pr-checks.yml` (the shape `tofu-intent` follows), the plan fields in the ADR's Context.
- **Required checks:** `pre-commit run --all-files`; `uv run pytest` from `tools/`.

## Risks

Could cause rework or delay but blocks nothing now — no live vulnerability, incident, or exposure window
([`docs/README.md#public-repo`](../README.md#public-repo)).

- The guard's tests use plan JSON from a built-in resource. The first plan of the real configuration may show a field
  or an action the tests did not; ADR 0102 names this as an assumption.
- A default of protecting every type makes a routine template bump need an entry each time. The safe-to-destroy list
  is where that is loosened, and it starts empty.
- `tofu graph` shows a `for_each` resource as one node, so a removed instance is not seen by the pull request check.
  None exist today.

## Open items

- Which types go on the safe-to-destroy list, and whether the template download and `terraform_data` replacements on a
  template bump belong there.
- The size at which G6 asks for an acknowledgement.
- Whether the plan before merge runs in a throwaway container on the operator host or in a plain worktree under the
  Tofu credentials' own user; no Docker rules exist for it yet.
- Whether a type should be flagged for review on an in-place update, if a real case shows an attribute change destroys
  in effect.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
