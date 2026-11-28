---
id: ADR-0122
revision: 0
type: adr
title: "Where coding-agent work is built and tried before delivery"
short: "Where coding-agent work runs"
solution: "Claude Code cloud sessions may do it alongside chat sessions, without the Claude GitHub App, and deliver series as before"
summary: "Where a coding agent can run a change before delivering it, without being able to alter what reaches main."
topic: security-hardening
status: accepted
related: [ADR-0050, ADR-0051, ADR-0055, ADR-0096, ADR-0112]
---

# 0122. Where coding-agent work is built and tried before delivery

## Problem

A change written by a coding agent should have run, containers included, before it is delivered, and the machine it runs in must not be able to alter what reaches `main`.

## Context

- A chat session cannot run containers, so Molecule scenarios and the Docker hooks first run after delivery.
- A Claude Code cloud session is a disposable virtual machine the provider operates, with Docker and a fresh clone. It needs [changes to its machine](../../topics/engineering/hosted-sessions.md#what-the-hook-prepares) for this repository's Molecule scenarios, none of them a documented feature of the environment.
- With the account's GitHub connection and without the Claude GitHub App on the repository, reads work and writes are refused: branch, pull request, comment, issue, commit, merge and `git push`, tried on a scratch repository connected that way.
- The agent is root in that machine and creates privileged containers there. The boundary is the provider's virtual machine, one to a session, not an account inside it. That differs from what [ADR 0051 (Coding-agent isolation)](../0051-coding-agent-execution-isolation/revision-000.md) asks of an own host.
- In a trial of one project stage, a session followed the delivery rules and ran the role's scenarios. Review then found a tag selection under which the change had no effect, and CI failed a coverage floor that neither the session nor the review had run.
- Running cloud sessions on one's own machines is offered to Team and Enterprise plans only.

**Threat model.** The adversary is a compromised or misdirected agent session, steered for one by content in a dependency or repository file. The asset is `main`, and through it every host a deploy reaches. The attack path is any write to the GitHub remote from the session, by `git`, an API, a connector or an app installed on the repository. Connector traffic does not pass through the environment's allowed list.

## Decision

Claude Code cloud sessions may do coding-agent work alongside chat sessions. Neither replaces the other, and no process requires a cloud session.

- The Claude GitHub App stays off the repository, and GitHub is connected without sending the `gh` token. This is how a session meets the property of [ADR 0050 (Agent changes to production)](../0050-agent-authored-changes-reaching-production/revision-000.md) that the agent's environment cannot write to the remote.
- A session delivers a [series](../../topics/engineering/landing-a-series.md) as every other source of changes does. The maintainer reviews and lands it, and CI is the authority on what passes.
- A session has no connectors and no scheduled or triggered runs, starts no subagents, reaches only the environment's default network list and named additions, and is kept private.

The settings that carry this are in [`hosted-sessions.md`](../../topics/engineering/hosted-sessions.md).

An own host stays the fallback, should the provider's terms or plans change.

## Alternatives considered

- **Chat sessions only.** Nothing new to trust or maintain, and role changes keep arriving without having run.
- **Cloud sessions with the Claude GitHub App, opening pull requests.** Saves the download and replay. The agent's environment can then write to the repository, and the series flow's local review goes.
- **Cloud sessions in place of chat sessions.** A trial of one stage does not show that a session can be relied on without the other, and the workarounds can break with an update.
- **Claude Code on an own host only.** Keeps the machine and its egress in the maintainer's hands, at the cost of a host and its upkeep before any change is run this way.

## Consequences

- The no-write property rests on settings held by two providers, not on where a credential is stored. The deny rules in the repository's settings guide a session and are not a security boundary.
- Prompts, files and command output are processed and stored by the provider, as in a chat session. Price, limits and terms are the provider's to change, and sessions share the account's usage limits.
- The test machine differs from CI ([where it differs](../../topics/engineering/hosted-sessions.md#where-it-differs-from-ci)).
- A session's report of what it verified is not evidence by itself.

## Invariants

- A cloud session cannot write to the repository's GitHub remote.
- Nothing a session writes reaches `main` except through the maintainer's landing.

## Non-goals

- Replacing chat sessions, or unattended agent runs.
- Work on any other repository.
- The own host's design, which [ADR 0051 (Coding-agent isolation)](../0051-coding-agent-execution-isolation/revision-000.md) and its neighbours hold.

## Validation

By hand: the refused writes are tried again, on a scratch repository, after a change to the GitHub connection or the environment.

## Reconsideration triggers

- A GitHub write from a session that cannot be refused.
- The machine's workarounds breaking often.
- Sessions delivering changes they never ran.
- A change in the provider's terms, price or plans that matters here.
