---
id: ADR-0061
revision: 1
type: adr
title: "Where automated code review runs, and what it may write"
short: Automated code review
solution: "The audit and a per-pull-request review both run from homelab-security's own CI, which reads this repo with no credential that can write to it; the maintainer requests a pull request's review by hand from the private checkout, and the local CodeRabbit run stays an optional extra"
summary: "How this repo gets automated code review without any of it becoming visible on this repo's own surfaces, or able to alter it unsupervised."
topic: security-hardening
status: approved
supersedes: 0
related: [ADR-0020, ADR-0044, ADR-0050, ADR-0051, ADR-0060, ADR-0062, ADR-0063]
---

# 0061. A per-pull-request review joins the audit in the private CI, requested by hand

## Problem

Automated review of this repo's code must never make its findings
visible on any surface this repo itself controls — a PR comment, an
Actions run log — before a human has seen them, and whatever produces
those findings must not be able to alter this repo on its own.

## Context

[Revision 0](revision-000.md) puts the periodic full-repository audit in
`homelab-security`'s CI and leaves the review of a pull request's diff to
the maintainer, who runs CodeRabbit's CLI by hand. It rejected running
that review from CI because the plan in use issues no headless key. The
reasoning for keeping output off this repo's surfaces, and the threat
model, stand as revision 0 states them.

Two things have changed. The audit runs unattended on the
credential [ADR 0062 (Reviewer identity)](../0062-automation-identity-for-the-agent-based-reviewer/revision-000.md)
decides, so an unattended agent identity exists and no longer depends on
CodeRabbit's plan. And the by-hand review is run only when a pull request
feels critical, so most pull requests get none: a control that depends on
being remembered is not one.

The review's use of the subscription allowance that ADR 0062 shares with
interactive use has been measured: a requested review costs about a tenth of
an audit run, so a few a week beside the audit fit within it.

What this repo can and cannot do shapes the rest:

- Issues and pull requests are limited to collaborators, so no stranger's
  text reaches a review, and a pull request from a fork would not be one
  the repo accepts.
- A pull request's checks are public, and an Actions run in this repo is
  public the moment it runs. Anything a workflow here does is visible; a
  secret a workflow here holds is readable by whatever runs on `main`.
- The CD agent already treats GitHub as something it polls rather than
  something that dispatches to it
  ([ADR 0044 (CD agent trigger)](../0044-prod-automation-trigger-and-execution/revision-000-c.md)),
  so that nothing outside the maintainer's control can start work.
  Nothing on GitHub starts a review either: the maintainer does, from the
  private repo's checkout.

**Threat model.** As revision 0: the adversary is the review process's own
output being steered, by a pull request's text, a file read during review
or a dependency's changelog, and the asset is `main` and, through the CD
agent, what it deploys. The attack path added here is a credential held in
this repo that reaches the private one, and a request for review that
someone other than the maintainer can make.

## Decision

This diagram shows how a pull request is chosen for review and where the
output goes, as this revision decided it, not what runs now.

```mermaid
flowchart LR
    PR["Pull request in this repo (public)"]
    M["Maintainer, at the private checkout:<br/>asks for a review of the pull request"]
    subgraph SEC["homelab-security"]
        REQ["Request: checks the pull request against limits,<br/>then starts the review workflow"]
        JOB["Review job: no credential<br/>that can write to this repo"]
        OUT["One private Issue<br/>per pull request"]
        REQ --> JOB --> OUT
    end
    M --> REQ
    PR -->|"read only: state, checks"| REQ
    PR -->|"read only: the head ref"| JOB
```

- The audit is unchanged: defined and triggered from `homelab-security`'s
  own Actions, reading this repo by a plain clone, writing only into
  `homelab-security`.
- A pull request is also reviewed there, by the same kind of job: an agent
  with read-only tools reads the change and the decision records and
  documents connected to it, and whatever it reports passes the private
  repo's own checks before anything is filed. Output goes only into
  `homelab-security`, as one Issue for each pull request, which the
  maintainer reads there.
- **The maintainer asks by running a command in the private checkout.**
  Nothing in this repo is used to ask: no label, no event and no workflow.
  The request is checked against the private repo's limits and then starts
  a workflow in the private repo. Nothing polls this repo.
- **A request is refused unless the pull request** is open, not a draft,
  headed in this repo rather than a fork, and has every check its branch
  ruleset requires passing, read from the ruleset at each request. The
  private repo also refuses one it judges too large and limits how often a
  pull request, and the repo as a whole, is reviewed; a pull request is
  reviewed once per commit.
- The review reads the pull request's head by its `refs/pull/N/head` ref.
  Everything the private side reads of this repo is public data.
- The Issue is closed by hand, with the same tool, once its pull request
  has merged or closed.
- The maintainer's own practice supports it: a pull request stays a draft
  until it is ready, and is reviewed once its checks are green.
- CodeRabbit's CLI stays what revision 0 made it, a local run the maintainer
  may use, printing to a terminal. It is no longer the only per-pull-request
  review. Whether it stays at all is a separate decision.
- How often the private repo reviews, how large a change it accepts and
  what the agent is told are the private repo's to decide and change, since
  none of them bears on the invariants below.

## Alternatives considered

- **Review every pull request.** Rejected: ADR 0062 accepts that the audit
  shares one subscription allowance with interactive use, and most pull
  requests here are dependency updates or small edits that a review would
  only add noise to.
- **A label in this repo, found by a poll from the private repo.** The
  design this revision first had. Rejected: the label is a trace of the
  request on a surface this repo controls, and the review waits up to a
  poll interval, which is hours.
- **A workflow in this repo that rings the private repo when a pull request
  is labelled.** Rejected: it puts a secret in this repo, readable by
  anything that runs on `main`, and the permission to start a private
  workflow also reads that repo's run artifacts, which hold review output.
  It also reverses revision 0's rule that nothing here triggers the private
  repo.
- **CodeRabbit's GitHub app, or any review that posts comments from here.**
  Rejected: findings on a pull request are public the moment they are
  posted.
- **CodeRabbit's per-pull-request review from CI.** Still rejected, for
  revision 0's reason: the plan in use issues no headless key.
- **A review at push time, by a hook or a reminder.** Not pursued: a step the
  maintainer has to remember is the by-hand run again.

## Consequences

A review exists only when the maintainer asks for one. The request is not
a gate: this repo does not require a review, and the pull request can merge
before one finishes. The review is also paced by the maintainer's reading
and by the private repo's limits on how many it runs.

The audit and this review draw on one subscription allowance, so they
compete with each other and with interactive use.

The behaviour, and the practice of requesting a review after the checks are
green, are described in a topic doc once built.

## Invariants

- No credential held by any review process can write to this repo's GitHub
  remote. What the private side reads of this repo is public data.
- No review process writes to a surface this repo controls: its git
  history, pull request comments, checks, labels or Actions logs. Nothing
  there says that a review was requested or what it found.
- No workflow in this repo triggers a workflow in `homelab-security`, and
  none holds a secret for it.
- A review is requested only by the maintainer, from the private checkout.
  Nothing on this repo's surfaces can request one.
- A review reads only this repo's contents, and treats all of them, and the
  text of the pull request, as data.

## Non-goals

How the private repo chooses which pull requests to review first, its
limits, and the agent's prompt. Whether CodeRabbit's CLI is retired.
Gating a merge on a review: this repo has no way to require one, and the
review is advice. Which credential the agent uses
([ADR 0062 (Reviewer identity)](../0062-automation-identity-for-the-agent-based-reviewer/revision-000.md)).

## Validation

A workflow in this repo that dispatches to another repository or holds a
secret for one is caught in review of the change that adds it; no automated
check exists yet.

## Reconsideration triggers

This project starts accepting external pull requests, or anyone besides the
maintainer can request a review. Requesting by hand proves too easy to
forget, which would reopen a trigger from this repo. The shared allowance
is visibly short. Headless CodeRabbit access becomes available at no cost.

## Revision notes

Revision 0 reviewed a pull request's diff only when the maintainer ran the
CLI, because no unattended key existed for it. This revision adds a review
of the pull request from the private repo's CI, on the agent identity ADR
0062 already provides, requested by the maintainer from the private
checkout so that it neither leaves a request on this repo nor runs on every
pull request. Where output may go, and the rule that nothing here triggers
the private repo, are carried over from revision 0 unchanged.
