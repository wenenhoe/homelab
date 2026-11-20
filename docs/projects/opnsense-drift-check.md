---
id: PROJ-opnsense-drift-check
title: "OPNsense Drift Check"
type: project
status: not-started
blocked: false
summary: "A scheduled --check --diff run of the gateway's play from the operator host that reports drift through a heartbeat, and a way to show what the check cannot see."
decision: ADR-0089/0
depends_on:
  - project: PROJ-operator-host
    reason: "The scheduled run needs the host that runs it, which that project builds."
---

# OPNsense Drift Check

What remains of [ADR 0089 (OPNsense configuration)](../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md)
once the gateway is rebuilt from the repository: the scheduled `--check --diff` run that reports
drift. The rest of the Decision is built and described in
[`opnsense-gateway.md`](../topics/infra/tofu/opnsense-gateway.md) and
[`opnsense-vm.md`](../topics/infra/tofu/opnsense-vm.md).

## Scope

A scheduled run of `playbooks/opnsense.yaml --check --diff` from the operator host that fails when
the check reports a change, and reports a missed run, through the job-heartbeat path of
[ADR 0072 (Job heartbeats)](../decisions/0072-detecting-scheduled-jobs-that-stop-running/revision-000.md).
Not in scope: the scheduled run of the flow list's probes, which
[`network-boundary-checks.md`](network-boundary-checks.md) owns and whose host and heartbeat this
run can share, and the CD agent's own application of the play ([`cd-agent.md`](cd-agent.md)).

## Decision

Implements [ADR 0089 (OPNsense configuration)](../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md),
`approved`: its Validation has a scheduled `--check --diff` run report drift.

## Execution plan

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The scheduled drift run and its heartbeat. Starts once the host that runs it exists | Not started | A clean check pushes the heartbeat, a check that reports a change or fails alerts through `OnFailure=`, and a run that does not happen alerts through the missing heartbeat, shown against a scratch gateway with a rule added by hand |

Stage status is `Not started`, `In progress`, or `Done`.

## Acceptance criteria

- [ ] A scheduled `--check --diff` run of the gateway's play pushes a heartbeat on a clean check and alerts on a reported change, a failure or a missed run.
- [ ] The settings that only the seed sets are shown by the run, or the project records that the seed's own tests are the check.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, set when the project starts.
- **Must not change:** the play's rules and the flow list.
- **Relevant files and interfaces:** `ansible/playbooks/opnsense.yaml`, the `opnsense_gateway` role, the job-heartbeat units of the monitoring role, [`opnsense-gateway.md`](../topics/infra/tofu/opnsense-gateway.md).
- **Required checks:** the project's tests and the scratch gateway's run with a hand-made rule.

## Open items

- How the run shows the settings only the seed sets (the hostname, time zone, SSH service, the
  GUI's listen interfaces, NTP and anti-lockout). A running gateway does not show them through the
  API, so the run does not read them back. Settle how, or accept the seed's own tests as the check.
- The legacy rule the seed holds on the untagged LAN is not listed by the rule API, so the check
  neither reports nor removes it.
- Whether any IPv6 rule remains in the gateway's firewall, which has not been looked at.
- Whether one scheduled job runs both this check and the flow list's probes, on the host and
  heartbeat [`network-boundary-checks.md`](network-boundary-checks.md)'s scheduled run uses.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
