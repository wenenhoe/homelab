# Security Findings Tracker

Code-review findings about this repo live in a separate private
repository, `homelab-security`, never here. This is a tracker, not a
mirror: it holds no code from this repo, and this repo holds no finding.
The reasoning is in
[ADR 0060](decisions/0060-tracking-and-managing-code-review-findings-for-a-public-repository/revision-000.md);
where the review itself runs, and what it may write, is
[ADR 0061](decisions/0061-where-automated-code-review-runs-and-what-it-may-write/revision-000.md).
The rule that keeps findings out of this repo is
[`README.md#public-repo`](README.md#public-repo).

## What the tracker holds

One YAML file per finding, named by a stable identifier. Each records a
severity, a file path in this repo, a description, a triage status
(`open`, `false-positive`, `fixed`, `accepted-risk`), the commit SHA of
this repo at the review that first produced it, and which reviewer
produced it. `homelab-security` owns the exact schema, in its own
`findings/SCHEMA.md`, and ships a validator that checks every file
against it. Raw review reports are not committed there; they stay as
workflow artifacts with a retention limit.

## Writing findings

Any workflow that writes findings follows one contract:

1. Skip a finding whose file already exists. An existing file is left
   as it is, whatever its status, so a triaged finding does not return.
2. Write new findings on a branch, adding files only.
3. Run the validator; on failure, push nothing.
4. Open a pull request and merge it at once. Opening it is what notifies
   the maintainer, and merging keeps the default branch current for the
   next run's check in step 1.

Findings can also be written by hand from the tracker's template.
Auto-merge is not used: it is unavailable on private repositories
without a paid plan, and waits on required checks that a pull request
opened with `GITHUB_TOKEN` starts only after someone approves the run.

## Triage

Triage happens outside CI. The maintainer bundles the open findings and
reviews them in a chat session, which sees only that upload and holds no
credential for the tracker. The outcome of a session is a patch to the
tracker that edits only each finding's status and reason, plus an
ordinary patch to this repo for each finding that needs a code change.

## Referring to findings from this repo

A commit message, patch, doc or comment here never mentions or describes
a finding, and never uses a finding's identifier. References run one
way: a fixed finding's reason in the tracker cites the commit in this
repo that fixed it.
