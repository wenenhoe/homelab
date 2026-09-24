---
id: PROJ-agent-full-repo-audit
title: "Agent-Based Full-Repo Audit"
type: project
status: not-started
blocked: false
summary: "A periodic coding-agent audit of the whole repo, ADR-aware, run from homelab-security's CI."
decision: ADR-0061/0
also_implements: [ADR-0062/0]
super_project: security-review-pipeline
depends_on:
  - project: PROJ-security-findings-repo
    reason: "The audit's output needs somewhere to be written before this can run."
---

# Agent-Based Full-Repo Audit

The half of [ADR 0061](../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md)
that covers what CodeRabbit's per-directory chunking structurally
can't: a coding agent, given the whole repo and its `docs/decisions/`
tree, distinguishing a real finding from one already reasoned through
and accepted (the shape of gap a sampled CodeRabbit finding on
`vault-bootstrap.hcl` demonstrated directly). Currently paused pending
this project's own de-risking.

## Scope

A periodic (starting weekly) `homelab-security` workflow: clone this
repo fresh, run a coding agent (leaning Claude Code, per
[ADR 0062](../decisions/0062-automation-identity-for-the-agent-based-reviewer/revision-000.md))
with access to the full clone plus `docs/decisions/` and
`docs/projects/`, instructed to read across files and docs as needed —
not confined to a fixed directory split — and to flag findings only
after checking whether an existing ADR already covers the behavior in
question. Output written into `homelab-security`
([ADR 0060](../decisions/0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-000.md)),
distinguishing "new, actionable" from "already covered by ADR NNNN."

Explicitly not in scope: implementing fixes, opening pull requests, or
writing anything to this repo — barred outright by
[ADR 0061](../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md).

## Decision

Implements [ADR 0061](../decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md),
`approved`. Also implements
[ADR 0062](../decisions/0062-automation-identity-for-the-agent-based-reviewer/revision-000.md),
currently `working` — this project cannot leave de-risking until that
revision reaches `approved`.

## Execution plan

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | De-risking spike: mint a token once with `claude setup-token` (it needs a browser approval, so it can't run unattended), store it as a `homelab-security` secret, then run `claude` unattended from a throwaway Actions run against a scratch clone | Not started | Resolves both of ADR 0062's open assumptions (reliability of the plain-CLI OAuth-token path; whether a dedicated account is warranted over the personal one) |
| 2 | Design the audit prompt and output schema: what the agent reads, what it checks for, how it writes into `homelab-security` | Not started | A dry-run against a real (non-scratch) clone produces a report a human would accept as useful, distinguishing new findings from ADR-covered behavior |
| 3 | First scheduled run | Not started | A full run completes unattended; every finding is human-reviewed in full before any of it is trusted |
| 4 | Steady-state cadence | Not started | Running weekly (or more often, once usage headroom against personal use is confirmed) with no manual intervention required per run |

## Acceptance criteria

- [ ] A scheduled run distinguishes findings already covered by an existing ADR from genuinely new ones.
- [ ] The agent never writes to this repo — no commit, no PR, no comment.
- [ ] ADR 0062 is `approved` before this project leaves de-risking.

## Agent handoff

This project is itself about building an agent-run pipeline. The stop
conditions in [`README.md#stop-conditions`](README.md#stop-conditions)
apply to whoever — human or agent — works its stages, same as any other
project; that includes stopping if the audit agent's own scope needs to
grow past reading-and-reporting into anything that writes to this repo.

- **Allowed to change:** the `homelab-security` repo, plus this project's own doc in this repo while it's active (whoever implements a stage records its progress there).
- **Must not change:** anything else in this repo. The audit job itself never writes here, per ADR 0061's invariants.
- **Relevant files and interfaces:** `docs/decisions/`, `docs/projects/` (what the agent reads); the finding schema from [`security-findings-repo`](security-findings-repo.md).
- **Required checks:** none in this repo's CI, since this project's changes live in `homelab-security`.

## Risks

- Subscription usage headroom competing with personal, interactive use of the same account (see ADR 0062's open assumptions).
- OAuth-token reliability in a plain CI step, unproven until stage 1's spike.

## Open items

- ADR 0062 must reach `approved` before stage 2 begins.
- Exact audit cadence beyond the initial weekly starting point.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
