---
id: PROJ-docs-corpus-compaction
title: "Docs corpus compaction"
type: project
status: building
blocked: false
summary: "Clean up the existing decisions and placeholder projects with the compaction rules: move unsettled questions to explorations, demote implementation-detail records, merge records that are one problem, and withdraw projects that wait on an unsettled revision."
allowed_paths:
  - docs/**
  - SECURITY.md
  - README.md
  - AGENTS.md
  - pyproject.toml
  - .github/**
  - ansible/**
  - docker/**
  - tools/**
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
- Records that are implementation detail are merged or demoted: the group on
  where OpenBao scripts, tooling and client code live and how the CLI is
  reached. A record whose content a topic doc already holds is demoted; one
  that holds a real choice is merged.
- Records that are one problem are merged into one lineage: the family on
  knowing that a pinned release, image digest, registry or hook is the one the
  publisher or reviewer meant.
- The secrets and Tofu clusters are reviewed for the same three outcomes.
- Projects that wait on a `working` revision are withdrawn or kept as spikes,
  one at a time.

A merge or demotion changes the record numbers and links that code comments,
configuration and tests mention, so those files are in the allowed paths for
that reference text alone; no behaviour changes in them.

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
| 1 | Unsettled questions | Done | Each candidate is read and is an exploration, a decision or dropped, and no `working` revision with no chosen solution remains unless a project is spiking it. |
| 2 | Implementation-detail records | Done | The OpenBao client, tooling-layout and CLI-access records are merged into three lineages that carry every decision of their sources, their numbers are former ids, and no link into a removed number remains. |
| 3 | Supply-chain family | Done | The accepted records on pinned-artifact trust are two lineages, provenance and image pinning with registry choice, that carry every Decision point, Invariant, Non-goal and trigger of their sources, list their numbers in `former_ids`, and have taken over their inbound links. The hooks-pinning record stays apart while it is `working`; re-run `suggest_adr_consolidation` once it is accepted. |
| 4 | Secrets and Tofu clusters | Done | Each cluster has been read, and every record in it is kept, condensed, merged or demoted. Merged: the expiry and OCI creation records, the R2 rotation-credential and admin-token records, and the recovery and snapshot-path records. Kept, each holding a separate choice: the path layout, catalog and ensure-module records, the host rebuild record, the re-init record, the Tofu credentials and DNS records, and the secret-storage root record. Approved and `working` records stay as they are until they are accepted. |
| 5 | Placeholder projects | Done | Each project that waits on a `working` revision is withdrawn or kept as a spike. Five whose spikes have not begun are `not-started`, waiting on their revision, and none is withdrawn because most are the only project naming theirs. The operator-host project stays `de-risking`, since its first stage is done. Eight projects are building and one is de-risking, so the planning view warns at nine until this project closes. |

Stage status is `Not started`, `In progress`, or `Done`. A stage is one pull
request per cluster, so a long run lands between clusters.

## Acceptance criteria

- [x] Every merge or demotion lists the numbers it removes, and the check for
      removed lineages passes.
- [x] No Decision point, Invariant, Non-goal or trigger of a source record is
      lost without a record of where it went.
- [x] `suggest_adr_consolidation` no longer lists a cluster that the maintainer
      decided to keep as separate records without a note saying why.
- [x] `pre-commit run --all-files` passes after each stage.

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

## Kept as separate records

`suggest_adr_consolidation` still lists these pairs and clusters. Each was
read and stays apart for the reason given.

| Records | Why they stay separate |
| :--- | :--- |
| ADR 0001 and 0002; 0001 and 0057 | The first two have the same shape but decide different things, host configuration through Ansible and proxy configuration through a checked-in Caddyfile, and each is a reason on its own. 0057 is abandoned. |
| ADR 0053, 0055, 0056 | Network reach of the coding-agent host, the maintainer's access to it, and the credentials the workstation holds are three boundaries with different owners. 0053 is `working`; 0055 and 0056 are `approved` and cannot merge into an accepted lineage. |
| ADR 0056 and 0058 | The credentials the workstation holds, and where operator work runs. 0058 is `working`. |
| ADR 0044, 0050, 0058 | How prod automation is triggered, how agent-written changes reach it, and where operator work runs are separate problems that cite one another. None is accepted. |
| ADR 0065 and 0068 | Where an app's definition merges with host intent, and where backup settings meet shared defaults. Each has its own resolver and its own invariants. |
| ADR 0107 and 0108 | Whether a pinned artifact is the publisher's, and which image a deploy runs and from where. The second states provenance as a non-goal and relies on the first. |
| ADR 0096 and 0108 | Hook pinning is `working` and has open assumptions. Re-read it once accepted. |
| ADR 0018 and 0023 | Unsealing OpenBao after a restart, and how credential code stores its output. 0018 is `working`. |
| ADR 0023, 0109, 0110 | Storage and rotation cadence, expiry, and the R2 admin token. They share a topic and link one another, but each states a different choice with its own triggers. |
| ADR 0037, 0080, 0082 | The documentation workflow, how an approved decision's reliance on an unfinished one is recorded, and how the next project is chosen. 0080 is `working`. |

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
