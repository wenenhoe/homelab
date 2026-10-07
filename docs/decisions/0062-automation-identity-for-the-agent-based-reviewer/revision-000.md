---
id: ADR-0062
revision: 0
type: adr
title: "Automation identity for the agent-based reviewer"
solution: "CLAUDE_CODE_OAUTH_TOKEN from the maintainer's personal Claude Pro/Max subscription, used only by the unmodified claude CLI in a private repository's CI"
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

The plain-CLI path has been exercised: a throwaway run of the unmodified
`claude` CLI in an ordinary GitHub Actions step, on a token minted this
way and with read-only tools, completed a task that needed the decisions
tree and the source read together. The subscription's usage limits are
shared across Claude and Claude Code, so the audit draws from the same
pool as interactive use.

## Decision

Use `CLAUDE_CODE_OAUTH_TOKEN`, minted via `claude setup-token` from the
maintainer's existing personal Pro/Max subscription and stored as a
`homelab-security` secret, matching
[ADR 0020](../0020-automation-identity-and-access-scope/revision-000.md)'s
per-consumer scoped-identity pattern. Sharing the subscription's usage
headroom with interactive use is accepted.

## Alternatives considered

- **Anthropic API key, metered billing.** Rejected for now: subscription
  usage is already paid for and, per the rough capacity check, sized for
  this volume — metered billing adds a second bill for no evident
  benefit at this scale.
- **OpenAI Codex via a ChatGPT Plus/Pro subscription.** A real
  equivalent path, not rejected outright — kept as the fallback if the
  Claude OAuth-token path proves unreliable in practice (see
  Reconsideration triggers).
- **A second, dedicated Anthropic account.** Rejected for now: it adds a
  second subscription fee to isolate the audit from personal usage
  headroom, and at this volume the shared pool is expected to absorb
  both. Revisited if the audit visibly competes with interactive use.

## Consequences

The token is valid for roughly a year and has no automated renewal path
(the flow it's generated from is browser-mediated) — regeneration is a
manual, calendar-driven task.

The audit and interactive use draw from one usage allowance, so a heavy
audit cycle can leave less of it for interactive work until the limits
reset.

## Invariants

The credential used for the audit agent authenticates only into
`homelab-security`'s workflow context; it is never exposed to or
reachable from this repo (see
[ADR 0061](../0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md)'s
invariants, which this narrows to the specific credential in question).
The workflow that uses it runs only in the maintainer's own private
repository, which nobody else can trigger, and calls the unmodified
`claude` binary; the token is never used on anyone else's behalf.

## Non-goals

Which vendor's model produces the better audit — a product judgment
revisited empirically as the pipeline runs, not an architectural one
settled here.

## Reconsideration triggers

The OAuth-token path proves unreliable in plain CI use. The audit
visibly competes with interactive use of the same account. Anthropic or
OpenAI changes subscription terms around automated or CI use in a way
that puts this out of policy.
