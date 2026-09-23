---
id: ADR-0062
revision: 0
type: adr
title: "Automation identity for the agent-based reviewer"
solution: "Leaning: CLAUDE_CODE_OAUTH_TOKEN from a Claude Pro/Max subscription, dedicated to automation rather than the personal daily-driver account"
summary: "Which credential the periodic full-repo audit agent authenticates with, and whose usage it draws from."
topic: security-hardening
status: working
related: [ADR-0020, ADR-0061]
---

# 0062. Automation identity for the agent-based reviewer

## Problem

The periodic full-repository audit
([ADR 0061](../0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md))
needs a standing, unattended credential to call a coding agent from
`homelab-security`'s CI. Deciding which one, and whose usage allowance it
draws from.

## Context

Anthropic's Claude Code documents `CLAUDE_CODE_OAUTH_TOKEN` — a
long-lived token generated once, interactively, by `claude setup-token`
— specifically for *"CI pipelines and scripts where browser login isn't
available,"* drawing from a Claude Pro/Max subscription rather than
metered API billing. OpenAI's Codex CLI has an equivalent subscription
login. [ADR 0020](../0020-automation-identity-and-access-scope/revision-000.md)
already establishes this repo's standing pattern: a scoped identity per
automated consumer, not a shared one.

A rough capacity check against this repo's real merge cadence (~4.2
merges/day average, bursty up to ~19 in a day) suggests the review
volume involved is modest — comfortably inside what a single Pro/Max
subscription's usage allowance should absorb, though this hasn't been
measured against the account's own personal, interactive usage yet.

## Decision

Leaning toward `CLAUDE_CODE_OAUTH_TOKEN`, minted via `claude setup-token`
and stored as a `homelab-security` secret, matching
[ADR 0020](../0020-automation-identity-and-access-scope/revision-000.md)'s
per-consumer scoped-identity pattern. Whether it's minted from the
existing personal Pro/Max subscription or a second, dedicated Anthropic
account is left open — see Assumptions.

## Alternatives considered

- **Anthropic API key, metered billing.** Rejected for now: subscription
  usage is already paid for and, per the rough capacity check, sized for
  this volume — metered billing adds a second bill for no evident
  benefit at this scale.
- **OpenAI Codex via a ChatGPT Plus/Pro subscription.** A real
  equivalent path, not rejected outright — kept as the fallback if the
  Claude OAuth-token path proves unreliable in practice (see
  Assumptions).

## Assumptions

- **Claim:** a dedicated second Anthropic account's subscription cost is
  worth the isolation from personal usage headroom, rather than reusing
  the existing personal account's token.
  **Breaks if wrong:** reuse the personal account's token instead,
  accepting shared usage headroom with interactive daily use.
  **Checked by:** running the weekly audit against the personal
  account's token for a few cycles and observing whether it visibly
  competes with personal use.
- **Claim:** `CLAUDE_CODE_OAUTH_TOKEN` is reliable enough when the
  `claude` CLI is called directly in a plain GitHub Actions step (not
  through a third-party wrapper action).
  **Breaks if wrong:** fall back to the Codex/ChatGPT-subscription
  equivalent path.
  **Checked by:** the de-risking spike in the
  [agent-full-repo-audit](../../projects/agent-full-repo-audit.md) project.

## Consequences

The token is valid for roughly a year and has no automated renewal path
(the flow it's generated from is browser-mediated) — regeneration is a
manual, calendar-driven task.

## Invariants

The credential used for the audit agent authenticates only into
`homelab-security`'s workflow context; it is never exposed to or
reachable from this repo (see
[ADR 0061](../0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md)'s
invariants, which this narrows to the specific credential in question).

## Non-goals

Which vendor's model produces the better audit — a product judgment
revisited empirically as the pipeline runs, not an architectural one
settled here.

## Reconsideration triggers

The de-risking spike shows the OAuth-token path is unreliable in plain
CI use. Anthropic or OpenAI changes subscription terms around automated
or CI use in a way that puts this out of policy.
