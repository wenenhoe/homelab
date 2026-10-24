---
id: PROJ-network-boundary-checks
title: Network Boundary Checks
type: project
status: de-risking
blocked: false
summary: A flow list, a probe runner and a canary VM per zone that show the firewall allows the declared flows between zones and blocks the rest, shared by the gateway, coding-agent and operator-host projects.
decision: ADR-0094/0
---

# Network Boundary Checks

Builds the one definition of a canary probe that three projects each promise: [`opnsense-config.md`](opnsense-config.md), [`coding-agent-egress.md`](coding-agent-egress.md) and [`operator-host-takeover.md`](operator-host-takeover.md). It is a project of its own, not a stage of the gateway project, because its flow list and runner are used by all three and outlive any one of them. Its first two stages need no gateway; the later ones need the scratch gateway that [`opnsense-config.md`](opnsense-config.md)'s Stage 2 builds.

## Scope

The flow list and its loader and rule checks, the probe module and runner, the canary VMs, the first flow entries for the existing zones, and the scheduled run with its heartbeat. It removes and renames nothing. Not in scope: the firewall rules and the flows each zone needs ([`opnsense-config.md`](opnsense-config.md), [`coding-agent-network.md`](coding-agent-network.md)), the egress proxy and the flow kind for requests through it ([`coding-agent-egress.md`](coding-agent-egress.md)), and reading `--check --diff` as drift (see Open items).

## Decision

Implements [ADR 0094 (Network boundary checks)](../decisions/0094-showing-the-network-boundary-behaves-as-declared/revision-000.md), `working`, so this project is `de-risking` until that revision's two open assumptions are resolved.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike on a scratch zone: whether the runner's host reaches a canary under the zones' rules, and whether connect and DNS flows cover what the three projects name. Starts once [`opnsense-config.md`](opnsense-config.md)'s Stage 2 has built a scratch gateway | Not started | Each assumption in ADR 0094 is resolved and folded into its Context, and the revision can be `approved` |
| 2 | The flow list's schema, loader and rule checks, with a pre-commit hook | Not started | The loader refuses a file that breaks each rule of the ADR, with a failing unit test per rule, and the hook runs on the flow list |
| 3 | The probe module and the runner | Not started | Against a fake canary each kind passes and fails as expected, a deny whose control fails is reported failed, a probe that cannot run fails the run, and the exit status is zero only if every selected probe passed |
| 4 | A canary VM and the first flows on the scratch gateway: the smoke flows and the existing zones | Not started | The runner against the scratch gateway passes every flow, and removing a rule that an allow flow depends on makes that probe fail |
| 5 | The scheduled run and its heartbeat. Starts once the host that runs it exists | Not started | A passing run pushes the heartbeat, a failing run alerts through `OnFailure=`, and a run that does not happen alerts as a missed heartbeat |

Stage status is `Not started`, `In progress`, or `Done`. Stages 2 and 3 need no VM and start once the revision is `approved`.

## Acceptance criteria

- [ ] One flow list in the repo is the only place the expected flows are written for checking, and its rules run as a pre-commit hook.
- [ ] The runner, started from the host that runs the play, tries each flow from a canary in the source zone, and every deny has a control that passed in the same run.
- [ ] The canary-probe criteria of [`opnsense-config.md`](opnsense-config.md) (Stages 3 and 4), [`coding-agent-egress.md`](coding-agent-egress.md) (Stage 2) and [`operator-host-takeover.md`](operator-host-takeover.md) (Stage 1) are met by this runner.
- [ ] A scheduled run pushes a heartbeat on a pass and alerts on a failure or a missed run.
- [ ] The resulting behavior is described in `docs/topics/infra/network-boundary-checks.md`.

## Agent handoff

- **Allowed to change:** not scoped yet; `allowed_paths` is added, in its own change, before an agent implements a stage.
- **Must not change:** the gateway play and its rules ([`opnsense-config.md`](opnsense-config.md)'s), the zones' decisions, and the existing heartbeat jobs.
- **Relevant files and interfaces:** `tools/utils/app_catalog.py` and `tools/ci/gates/app_catalog_rules.py` (the loader-and-rules-hook pattern to follow), `docs/topics/engineering/ci/gates.md`, `docs/topics/monitoring/gatus.md` and `ansible/roles/gatus_push` (the heartbeat path).
- **Required checks:** `pre-commit run --all-files`, and `uv run pytest` from `tools/`.

## Risks

- The flow list is a third statement of intent beside the gateway play and the topic doc. Only the probes tie it to the play.
- Stage 4 waits on the scratch gateway and Stage 5 on the host that runs the job; that host's project is still de-risking ([`operator-host.md`](operator-host.md)).
- A canary needs inbound SSH in each zone. A zone whose decision limits inbound flows, such as [ADR 0053 (Coding-agent network reach)](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md), may need a revision to admit it.
- A canary per zone adds VMs to a node with limited headroom.

## Open items

- Reading drift on the gateway: [`opnsense-config.md`](opnsense-config.md)'s Open items state the question. If the answer is code under `tools/`, it joins this project as a stage or becomes a project of its own, under a decision written once real `--check --diff` output has been kept.
- Whether a pre-merge CI job can boot the pinned pre-installed gateway image under QEMU depends on KVM being available on the runners, which has not been checked. Whether it belongs here, in [`opnsense-config.md`](opnsense-config.md) or in a project of its own is decided after that check.
- Whether a static check ties the gateway play's rule variables to the flow list. It cannot show effective rule order, so it complements the probes. Decide it with [`opnsense-config.md`](opnsense-config.md)'s Stage 3, when the rules exist.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
