---
id: PROJ-coding-agent-molecule-runtime
title: Coding-Agent Molecule Runtime
type: project
status: not-started
blocked: false
summary: Choose and adopt a container runtime that runs the repo's privileged, systemd-based Molecule scenarios without host-level root on the coding-agent host.
decision: ADR-0052/0
super_project: coding-agent-host
track: workflow
phase: 2-molecule-runtime
depends_on:
  - project: PROJ-coding-agent-host
    reason: The runtime must be validated on the isolated host it will run on, not a stand-in
---

# Coding-Agent Molecule Runtime

Makes the repo's Molecule scenarios runnable on the coding-agent host. Staged because the runtime is chosen by running the real fixtures against up to three candidates, and only then adopted and documented.

## Scope

Comparing rootless Podman, rootless Docker, and a microVM-private daemon against `compose/default` and `secrets/vault_backed`; adopting the winner in the `coding_agent` role; naming which scenarios the host runs. Not in scope: the host ([`coding-agent-host.md`](coding-agent-host.md)) and CI's own Molecule runs.

## Decision

Implements [ADR 0052](../decisions/0052-molecule-runtime-without-host-privilege/revision-000.md), `working`.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike each candidate against `compose/default`, then `secrets/vault_backed` | Not started | One candidate passes, or none does and the outcome is recorded in ADR 0052 |
| 2 | Adopt the chosen runtime in the `coding_agent` role | Not started | The role installs and configures it idempotently and no host-root daemon socket is reachable from the agent account |
| 3 | Run the scenario set the host claims and name the subset in `molecule-testing.md` | Not started | The named scenarios pass from `ansible/scripts/molecule-test-all.sh` on the host |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] ADR 0052 names one runtime and its Assumptions section is gone.
- [ ] The scenarios the host claims pass on the host.
- [ ] No host-root daemon socket is reachable from the agent account.
- [ ] The scenario subset, if reduced, is stated in `molecule-testing.md`.

## Agent handoff

- **Allowed to change:** not scoped yet; `allowed_paths` is added, in its own change, before an agent implements a stage.
- **Must not change:** scenario fixtures or the `molecule-dind` image to make a candidate pass; a needed fixture change is a stop condition.
- **Relevant files and interfaces:** `ansible/roles/compose/molecule/default/molecule.yml`, `ansible/roles/molecule_helpers/tasks/start_openbao_test_target.yaml`, `docker/molecule-dind/`.
- **Required checks:** `pre-commit run --all-files`; the adopted scenarios.

## Risks

- If only the microVM-private candidate passes, [ADR 0051](../decisions/0051-coding-agent-execution-isolation/revision-000.md) reopens and nested virtualization returns to the table. That is a stop condition, not a stage.
- Coverage on the host may be a subset of CI's.

## Open items

- Time-box per candidate.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] The linked revision is `accepted`, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
