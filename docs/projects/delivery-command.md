---
id: PROJ-delivery-command
title: "Delivery Command"
type: project
status: building
plan: confirmed
blocked: false
summary: "One command that builds, checks and hands over a series, replacing the hand recipe, with and without Docker."
decision: ADR-0123/0
allowed_paths:
  - tools/deliver_series/**
  - tools/tests/deliver_series/**
  - AGENTS.md
  - docs/topics/engineering/conventions.md
  - docs/topics/engineering/delivering-a-series.md
  - docs/topics/engineering/landing-a-series.md
  - docs/topics/engineering/checks-without-docker.md
  - docs/topics/engineering/hosted-sessions.md
---

# Delivery Command

Builds `tools/deliver_series`, so an agent runs one command where it now follows a recipe. It is staged because building a checked series file is useful before the replay and the probes are.

## Scope

- A new `tools/deliver_series` and its tests.
- The docs it replaces: the recipe in [`checks-without-docker.md`](../topics/engineering/checks-without-docker.md#verifying-a-series-before-delivery) and the delivery bullets in [`AGENTS.md`](../../AGENTS.md#rules-for-a-coding-agent), which keep the rules and lose the steps.

Not in: any change to `land_series`, running Molecule, support for a second repository, and the security repository's delivery.

## Decision

[ADR 0123 revision 0 (Preparing a series)](../decisions/0123-preparing-a-series-for-delivery/revision-000.md).

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Check the commits and build the series | Done | From a plan of layers, the command writes a series file `land_series` reads, outside the checkout, and refuses a stale base, a changed tree and a commit without the commit form. Tests cover each refusal. |
| 2 | Replay, probes and handover | Not started | The same command replays the series and the push stage, skips only hooks whose need a probe found missing, and prints the handover. It has run in a session with Docker and in one without. The docs it replaces are cut. |

**Plan input.** One line per layer, in order: slug, number of commits, and a title, which a layer of one commit may leave out. Numbering starts at `0001`, or after the ids of series files named as not yet merged.

**Commit form.** The maintainer's identity as [the commit form](../topics/engineering/conventions.md#commits) reads it, a Conventional Commits subject of at most 72 characters, dates at `+0800`, one `Co-Authored-By` trailer, only `Plan-Confirmed:` or `Editorial-Fix:` beside it, and no session link.

**Needs to probe.**

| Need | Hooks | Without it |
| :--- | :--- | :--- |
| A Docker daemon | `dclint-docker`, `hadolint-docker`, `actionlint-docker` | skipped |
| A download of the Go toolchain | `gitleaks` | skipped |
| The GitHub API | `zizmor` | skipped |
| The Ansible collections | `ansible-lint` (push stage) | skipped |

A test fails when the pre-commit configuration holds a Docker hook that is not listed. In a [cloud session](../topics/engineering/hosted-sessions.md) `zizmor` can fail with a 401 though the API answers, and the collections are present only once installed.

**Handover.** The maintainer's replay and `--land` commands are those of [`landing-a-series.md`](../topics/engineering/landing-a-series.md#replay), and a test holds the two equal.

## Acceptance criteria

- [ ] A series is built, checked and handed over with one command, in a session with Docker and in one without.
- [ ] A hook whose need is met is never skipped, and every skipped hook is named with its reason.
- [ ] The command refuses to run where `CLAUDE_CODE_REMOTE` is not `true`.
- [ ] No doc still tells an agent to carry out a step the command does.

## Agent handoff

- **Allowed to change:** the `allowed_paths` above: the command and its tests, `AGENTS.md`, and under `docs/topics/engineering/` the pages on delivery, landing, checks and cloud sessions.
- **Must not change:** `tools/land_series/`, the pre-commit configuration, `.claude/`.
- **Relevant files and interfaces:** `land_series.replay.stopped_by` and `STOP_PREFIXES`, `land_series.manifest.parse_series`, and `land_series --dry-run --accept-stops`.
- **Required checks:** the unit tests, and a real run of the command on this project's own series.

## Open items

- How long a replay takes in each kind of session.
- Which of the probed hooks run in a cloud session.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
