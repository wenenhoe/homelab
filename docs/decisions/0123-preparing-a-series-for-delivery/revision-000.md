---
id: ADR-0123
revision: 0
type: adr
title: "Preparing a series so no step of its recipe is carried out by hand"
short: "Preparing a series"
solution: "One command that checks the commits, builds the series file, replays it skipping only what the machine cannot run, and prints the handover"
summary: "How the author of a series builds and checks it before handing it over."
topic: repository-tooling
status: approved
weight: light
related: [ADR-0037, ADR-0112, ADR-0122]
---

# 0123. Preparing a series so no step of its recipe is carried out by hand

## Problem

A series must be handed over built on the current base, in the commit form, checked as far as the machine allows, with what was not checked said.

## Context

- The recipe is carried out by hand. A trial session skipped the replay and gave commands that would have landed nothing.
- A hand-typed skip list has named hooks the repository does not have, and nothing said so.
- Chat sessions and cloud sessions both write series ([ADR 0122 (Where coding-agent work runs)](../0122-where-coding-agent-work-is-built-and-tried/revision-000.md)). A cloud session has Docker. A chat sandbox without a daemon also had `CLAUDE_CODE_REMOTE` set to `true`.
- There the Docker hooks, `gitleaks` and `zizmor` could not run.
- Nothing checks a commit's identity, dates or trailer ([commit form](../../topics/engineering/conventions.md#commits)).
- A replay with no terminal needs `--accept-stops`, which [ADR 0112 (Landing a patch series)](../0112-landing-a-series-of-dependent-changes-on-main/revision-004.md) keeps for a machine that is thrown away and holds no credential.

## Decision

`tools/deliver_series` takes the commits on top of the base and a plan of one line per layer.

- It fetches the base and refuses a branch that is not on its tip, or a tree with changes.
- It checks each commit's form and writes the series file outside the checkout.
- It probes what the machine has and skips only a hook whose need is not met, naming the reason. It installs nothing.
- It replays on a fresh clone and runs the push-stage hooks of each pull request.
- It runs only where `CLAUDE_CODE_REMOTE` is `true`, which does not show that a machine is disposable, and replays a commit on the stop list only when told its patch was read.
- It runs no Molecule scenario and lists each changed role as not verified.
- It prints the layers, those on the stop list or touching a hook, CI or tooling path, what was skipped, and the maintainer's commands.
- It reuses `land_series`'s stop list without changing that tool, and holds what is particular to this repository in one object. Nothing is built for a second one.

## Alternatives considered

- **Trim the prose by hand.** The steps stay manual, which is where the trial failed.
- **Claude Code hooks.** They act in one tool and guard from inside the agent's own environment.
- **Choosing skips by kind of session.** The sandbox above shows no reliable sign of it.
- **A commit-form check in `land_series` or a `commit-msg` hook.** A change to that tool is applied by hand, and a hook runs only where installed.
- **Running Molecule in the command.** Slow, and only possible with Docker.

## Reconsideration triggers

Parallel Molecule runs become reliable enough to run on every delivery; a second repository needs the command; a session's failures turn out to be judgement, which no command would catch.
