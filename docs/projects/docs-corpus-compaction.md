---
id: PROJ-docs-corpus-compaction
title: "Docs corpus compaction"
type: project
status: not-started
blocked: false
summary: "Clean up the existing decisions and placeholder projects with the compaction rules: move unsettled questions to explorations, demote implementation-detail records, merge records that are one problem, and withdraw projects that wait on an unsettled revision."
allowed_paths:
  - docs/**
  - SECURITY.md
---

# Docs corpus compaction

Applies the rules of
[ADR 0037 revision 4 (Decision and project workflow)](../decisions/0037-decision-and-project-documentation-workflow/revision-004.md)
to the records already in the repository. It is staged by cluster because each
cluster is read in full and reviewed alone: a merge or a demotion that loses a
Decision point cannot be told from a clean one by a check.

## Scope

- Unsettled questions now filed as `working` revisions that choose nothing move
  to `docs/explorations/`, or become a light or full decision if one was
  chosen. Candidates: the intrusion-detection and security-event-collection
  records, and the open revisions of the certificate-issuance and
  certificate-lifetime records. Each is read before it moves.
- Records that are implementation detail are demoted: the group on where
  OpenBao scripts, tooling and client code live and how the CLI is reached.
  Their content goes to a topic doc or the conventions first.
- Records that are one problem are merged into one lineage: the family on
  knowing that a pinned release, image digest, registry or hook is the one the
  publisher or reviewer meant.
- The secrets and Tofu clusters are reviewed for the same three outcomes.
- Projects that wait on a `working` revision are withdrawn or kept as spikes,
  one at a time.

Not in scope: changing what any accepted decision decided. That is an ordinary
revision first. New checks or tools: the compaction tools already exist, and a
gap in them is its own change.

## Decision

None is needed: the rules are set by
[ADR 0037 revision 4](../decisions/0037-decision-and-project-documentation-workflow/revision-004.md).

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Unsettled questions | Not started | Each candidate is read and is an exploration, a decision or dropped, and none remains as a `working` revision with no chosen solution. |
| 2 | Implementation-detail records | Not started | The OpenBao placement records are demoted or condensed, their content is in a topic doc, their numbers are in the ledger of removed numbers, and no link into them remains. |
| 3 | Supply-chain family | Not started | The records on pinned-artifact trust are one lineage that carries every Decision point, Invariant, Non-goal and trigger of its sources, lists their numbers in `former_ids`, and has taken over their inbound links. |
| 4 | Secrets and Tofu clusters | Not started | Each cluster has been read, and every record in it is kept, condensed, merged or demoted, with the outcome recorded in the pull request. |
| 5 | Placeholder projects | Not started | Each project that waits on a `working` revision is withdrawn or kept as a spike, and the number of active projects is at or under the limit the planning view warns on. |

Stage status is `Not started`, `In progress`, or `Done`. A stage is one pull
request per cluster, so a long run lands between clusters.

## Acceptance criteria

- [ ] Every merge or demotion lists the numbers it removes, and the check for
      removed lineages passes.
- [ ] No Decision point, Invariant, Non-goal or trigger of a source record is
      lost without a record of where it went.
- [ ] `suggest_adr_consolidation` no longer lists a cluster that the maintainer
      decided to keep as separate records without a note saying why.
- [ ] `pre-commit run --all-files` passes after each stage.

## Agent handoff

Compaction is made by the maintainer. An agent prepares the merge or demotion
for a cluster and stops for review; it never merges the cluster itself.

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the Problem, Decision, Invariants, Non-goals and
  Reconsideration triggers of an `accepted` revision that is condensed in
  place.
- **Relevant files and interfaces:** [`docs/decisions/README.md`](../decisions/README.md#compacting-accepted-records)
  for the operations, `docs/decisions/removed.md` for the ledger, and
  `tools/doc_scripts/suggest_adr_consolidation.py` for candidates.
- **Required checks:** `pre-commit run --all-files`.

## Risks

- A merge that quietly drops a Decision point. Each is compared point by point
  against its sources in the pull request.
- Withdrawing a project loses its stage plan until the revision is approved
  again, so each is decided alone.

## Open items

- Which of the projects that wait on a `working` revision are withdrawn and
  which stay as spikes.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
