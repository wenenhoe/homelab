---
id: EXP-agent-instruction-load
title: "How can the rules a coding agent follows be cut down without losing what they protect?"
type: exploration
status: open
summary: "Which delivery and agent rules a check or a tool could carry, so that less has to be read and carried out by hand."
topic: documentation-process
related: [ADR-0037, ADR-0112]
---

# How can the rules a coding agent follows be cut down without losing what they protect?

An agent working a project stage reads `AGENTS.md` and the docs it names before it changes anything, and then carries out delivery by hand. How much of that can move into a check or a tool, and what has to stay prose, depends on which rules code already holds and on trials of real work.

## What bears on it

### What is read

For a project stage that delivers code from a cloud session, approximately:

| Doc | Words |
| :--- | ---: |
| [`AGENTS.md`](../../AGENTS.md) | 1,700 |
| [`landing-a-series.md`](../topics/engineering/landing-a-series.md) | 3,400 |
| [`projects/README.md`](../projects/README.md) | 3,200 |
| [`decisions/README.md`](../decisions/README.md) | 3,100 |
| [`conventions.md`](../topics/engineering/conventions.md) | 2,000 |
| [`checks-without-docker.md`](../topics/engineering/checks-without-docker.md) and [`hosted-sessions.md`](../topics/engineering/hosted-sessions.md) | 2,000 |

`landing-a-series.md` serves two readers: the agent that writes a series, and the maintainer who runs the tool and acts when it stops.

Instructions kept outside the repository for chat sessions repeat some of the delivery rules, and a session in Claude Code does not receive them.

### What a trial showed

One session, given a project's name, skipped the replay, gave final commands that would have landed nothing, left the series file on its own machine and built from a clone one merge old. The first three are steps of a manual recipe. The last would have happened however short the docs were. One run does not show that length caused any of them.

A later delivery of a project stage failed [the Molecule coverage floor](../topics/engineering/ci/gates.md#molecule-coverage-gate) in CI. The floor was named in no doc `AGENTS.md` sends a session to for delivery, and nothing run before the pull request checked it. [A full run of a role](../topics/testing/molecule-testing.md#coverage) now checks it, with no rule added to `AGENTS.md`.

### What holds each rule today

| Rule | Held by |
| :--- | :--- |
| Series manifest, layer ids, slugs and the form and length of a `# title` | `land_series`, when it reads the file |
| A project's `allowed_paths`, start and close, and doc drift | Checkers, at commit, replay and CI |
| Generated views stay out of a patch | `.gitignore` |
| Checks pass on every commit | The replay and CI, whether or not the author ran them |
| A role's Molecule coverage floor | CI, and `molecule-test-all.sh` after a full run of the role; where Molecule cannot run, CI alone |
| No write to GitHub | A cloud session's connection refuses it, and [deny rules](../topics/engineering/hosted-sessions.md#what-the-repository-sets) guide the agent |
| No session link | A setting, in Claude Code only |
| Commit identity, subject, dates and trailer | Nothing found that checks a commit |
| Work from the current base | Prose only; a stale series that still applies would pass |
| Replay before delivering, attach the file, give the maintainer's commands, name the stop-list layers | Prose only |
| The public-repo rule, data classification, stop conditions, what deserves a decision, comment discipline, verifying before claiming | Judgement; a checker holds only narrow parts, such as the form of a command block |

The table covers delivery and the rules in `AGENTS.md`. The decision and project docs have not been read rule by rule.

### What a hook can do

Claude Code [hooks](https://code.claude.com/docs/en/hooks) can refuse a tool call before it runs, add text for the model after one succeeds or fails, and keep a session from ending with a reason. A checker's failure already reaches an agent in the command's output, so how to fix it belongs in the checker's message, which a chat session, CI and a person read too. A hook adds something where nothing fails on its own: a commit that skips the checks, or a session that ends with commits and no replayed series. It acts only in Claude Code, and a change to `.claude/` is on [the stop list](../topics/engineering/landing-a-series.md#the-stop-list).

## Options

- **Trim the prose by hand.** No code. The steps stay manual, which is where the trial failed.
- **One delivery command.** It would fetch the base and refuse a stale one, build the series file, replay it on a fresh clone with the push-stage hooks, and print what was skipped, the stop-list layers and the maintainer's commands. The instructions it replaces go in the same series. Costs code and tests, on the stop list. It works in any session that can run Python and clone the repository.
- **A commit-form check** in the replay or a `commit-msg` hook. Small. A change to `land_series` is applied by hand.
- **Fix advice in checker messages.** Lets prose about what a checker enforces shrink to a line. Spread over many checkers.
- **Claude Code hooks.** Catch what no command fails on. One tool only, and the guard is the agent's own environment, not a boundary.
- **Split docs by reader.** What an author must do apart from how a tool behaves. No rule is lost, and there is more than one place to keep right.

## Still to check

- Whether a session can make the replay's clone, and how long a replay takes there.
- What a second trial, started from the current `main`, gets wrong.
- Whether a session runs a role's scenarios through `molecule-test-all.sh`, where the coverage check is, or one `molecule test` at a time.
- Which rules in the decision and project docs a checker already enforces.
- Whether a hook can tell reliably that a delivery happened, without keeping a session from ending when there is nothing to deliver.

## Leaning

The delivery command first, deleting what it replaces, then advice in checker messages. Hooks only for what neither can catch. A new rule is added after something has gone wrong, and only once a check has been ruled out. What would change it: a trial whose failures are mostly judgement, which no tool would help.
