---
id: EXP-agent-instruction-load
title: "How can the rules a coding agent follows be cut down without losing what they protect?"
type: exploration
status: open
summary: "Which delivery and agent rules a check or a tool could carry, so that less has to be read and carried out by hand."
topic: documentation-process
related: [ADR-0037, ADR-0112, ADR-0122, ADR-0123]
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

A second trial was a rehearsal: a fresh session, given only a project's name, read what `AGENTS.md` sends it to and answered eleven questions about what it would do, changing and running nothing. It fetched first, read the project's `decision:` revision and fields, stopped on a path outside `allowed_paths`, named `molecule-test-all.sh` without `-s` for the coverage floor, wrote the commit form whole, declined the push and `--reset-author`, and described `deliver_series` and the handover correctly. It opened sixteen docs, five of them by search only, and said it would skip most of the project lifecycle, the maintainer's side of `landing-a-series.md` and `checks-without-docker.md` next time. What it said it would do is not what it does, so this shows the docs can be followed and not that a session follows them.

Three questions it could not answer from a doc. No doc says how a task that stops on scope is handed back, or how an agent that finds an unfixed weakness tells the maintainer. And the stop list names a workflow and an action while the handover names every layer that touches a CI path, so the session could not tell whether `.github/molecule-shards.yml` counts as one.

### Where the prose has drifted

The replay went from asking at each commit on the stop list to asking once for the series. [The rules for a coding agent](../../AGENTS.md#rules-for-a-coding-agent) were written after that and worded the stop list as stopping for each layer. A [rule for cutting a series](../topics/engineering/landing-a-series.md#cutting-a-series) still kept a stop-list layer apart so that the confirmation attached to its code.

The clone to start from was described unevenly. `AGENTS.md` had a session fetch the base, [the commit form](../topics/engineering/conventions.md#commits) asked for a depth of 50 at least, and [`checks-without-docker.md`](../topics/engineering/checks-without-docker.md) asked for the whole history, without which a moved-file check passes unrun, while its replay recipe cloned to a depth of 50.

### What holds each rule today

| Rule | Held by |
| :--- | :--- |
| Series manifest, layer ids, slugs and the form and length of a `# title` | `land_series`, when it reads the file |
| Which layer a change goes in, and which branch the series targets | Prose only; the replay checks that each commit passes, and `land_series` the form of a `# base:` line |
| A project's `allowed_paths`, start and close, and doc drift | Checkers, at commit, replay and CI |
| Generated views stay out of a patch | `.gitignore` |
| Checks pass on every commit | The replay and CI, whether or not the author ran them |
| A role's Molecule coverage floor | CI, and `molecule-test-all.sh` after a full run of the role; where Molecule cannot run, CI alone |
| No write to GitHub | A cloud session's connection refuses it, and [deny rules](../topics/engineering/hosted-sessions.md#what-the-repository-sets) guide the agent |
| No session link | A setting, in Claude Code only |
| Commit identity, subject, dates and trailer | Nothing found that checks a commit |
| Work from the current base | Prose only; a stale series that still applies would pass |
| Replay before delivering, attach the file, give the maintainer's commands, name the stop-list layers | Prose only |
| A project's status against its decision revision's state and its stage table, `plan: draft`, `allowed_paths`, the start gate and the close | `check_doc_drift`, `check_project_start`, `check_project_scope` and `check_project_close` |
| A decision lineage: one `approved` revision, no assumptions on an `approved` one, the frozen sections of an `accepted` or `superseded` one, a `**Status:**` body line, the length of a light record | `check_doc_drift` and `check_accepted_records` |
| Which edits an agent may make to an `approved` or `accepted` revision | Prose only, apart from the frozen sections of an `accepted` one |
| Condensing a revision before it is set `accepted`, the closing checklist, updating the stage table in each pull request that works a stage | Prose only; nothing checks that the condensing was done |
| The public-repo rule, data classification, stop conditions, what deserves a decision, comment discipline, verifying before claiming | Judgement; a checker holds only narrow parts, such as the form of a command block |

The table covers delivery, the rules in `AGENTS.md`, and the lifecycle rules of [`decisions/README.md`](../decisions/README.md) and [`projects/README.md`](../projects/README.md), which the checkers hold for the most part. What stays prose there is the edit an agent may make to a revision, the condensing at close and the checklist, which is also the judgement that [the stop conditions](../projects/README.md#stop-conditions) ask for. The task docs outside these two have not been read rule by rule.

### What a hook can do

Claude Code [hooks](https://code.claude.com/docs/en/hooks) can refuse a tool call before it runs, add text for the model after one succeeds or fails, and keep a session from ending with a reason. A checker's failure already reaches an agent in the command's output, so how to fix it belongs in the checker's message, which a chat session, CI and a person read too. A hook adds something where nothing fails on its own: a commit that skips the checks, or a session that ends with commits and no replayed series. It acts only in Claude Code, and a change to `.claude/` is on [the stop list](../topics/engineering/landing-a-series.md#the-stop-list).

## Options

- **Trim the prose by hand.** No code. The steps stay manual, which is where the trial failed.
- **Fix advice in checker messages.** Lets prose about what a checker enforces shrink to a line. Spread over many checkers.
- **Claude Code hooks.** Catch what no command fails on. One tool only, and the guard is the agent's own environment, not a boundary.
- **Split docs by reader.** What an author must do apart from how a tool behaves. No rule is lost, and there is more than one place to keep right.

## Still to check

- Whether a session that does the work, and does not describe it, runs a role's scenarios through `molecule-test-all.sh` or one `molecule test` at a time, and what a trial of a task that names no project gets wrong.
- Which rules in the topic docs a delivery touches, such as `docs/README.md` and the security policy, a checker already enforces.
- Whether a hook can tell reliably that a delivery happened, without keeping a session from ending when there is nothing to deliver.

## Leaning

The delivery command [ADR 0123 (Preparing a series)](../decisions/0123-preparing-a-series-for-delivery/revision-000.md) decides comes first. What stays open here is what it does not reach: advice in checker messages next, then hooks only for what neither can catch. A new rule is added after something has gone wrong, and only once a check has been ruled out. What would change it: a trial whose failures are mostly judgement, which no tool would help.
