---
id: PROJ-cd-agent
title: CD Agent Host
type: project
status: building
blocked: false
summary: A dedicated, pull-based automation host that runs the deploy, maintenance, and freshness jobs.
decision: ADR-0044/0-c
super_project: pull-based-cd
track: agent
---

# CD Agent Host

Replaces manual `ansible-playbook` deploys and rotation runs with a
dedicated, pull-based automation host. The second half of the
OpenBao+CD-agent migration this repo originally scoped together —
OpenBao itself is done; see ADRs
[0017](../decisions/0017-recovering-the-secrets-store-from-total-loss/revision-000.md) through
[0026](../decisions/0026-detecting-reads-of-high-value-secrets/revision-000.md)
and the `openbao-*.md` docs for that half.

This is the first of three projects in the `pull-based-cd` initiative; [`cd-agent-approles.md`](cd-agent-approles.md) and [`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md) cover its AppRoles and retiring `controller`'s standing AppRole.

## Scope

The `cd_agent` host: a dedicated LAN box with a fixed IP and no job-serving listener (SSH from the operator host only), running the jobs that replace manual `ansible-playbook` deploys and rotation runs. Not in scope: its AppRoles ([`cd-agent-approles.md`](cd-agent-approles.md)) and retiring `controller`'s standing AppRole ([`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)).

## Decision

Implements [ADR 0044 revision 0-c (CD agent trigger)](../decisions/0044-prod-automation-trigger-and-execution/revision-000-c.md), `approved`. Candidates [000-a](../decisions/0044-prod-automation-trigger-and-execution/revision-000-a.md) and [000-b](../decisions/0044-prod-automation-trigger-and-execution/revision-000-b.md) are abandoned.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | `cd_agent` host — dedicated LAN box, fixed IP, one timer and one unprivileged user per job for deploy/maintenance/freshness, and the hardening baseline's role | In progress | The host runs the deploy, maintenance, and freshness jobs, each as its own user from a clean checkout of `origin/main`, with only `sshd` listening |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — `cd_agent` host

A dedicated LAN host with a fixed IP, in none of `managed_hosts`,
`app_hosts`, or `patched_hosts`. One systemd timer per job; each job's
unit runs as its own unprivileged user, fetches `origin/main`
anonymously into its own state directory, checks out the commit as a
clean tree, and runs the playbook or `tools/` entry point from it. The
poll, decide and run step is [`tools/cd_agent/run_job.py`](../../tools/cd_agent/run_job.py), unit-tested and described in [`cd-agent-runner.md`](../topics/deploy/cd-agent-runner.md). The host's
only inbound service is `sshd`, accepted from the operator host alone. The `cd_agent` role ([`cd-agent-host.md`](../topics/deploy/cd-agent-host.md)) builds the users, units and `sshd` restriction from a `cd_agent_jobs` list. The `cd_agent` inventory group, the jobs' definitions in its group variables and `playbooks/cd-agent.yaml` apply it. Rotation is [`cd-agent-rotation.md`](cd-agent-rotation.md)'s.
The freshness job replaces the weekly user timer on `controller` (`tools/cloud_credentials/systemd/`), running as a plain weekly timer on this always-on host. See the [decision](../decisions/0044-prod-automation-trigger-and-execution/revision-000-c.md) this stage implements.

## Acceptance criteria

- [ ] Each of the deploy, maintenance, and freshness jobs runs from its own timer, as its own user, from a clean checkout of `origin/main` it fetched itself.
- [ ] Only `sshd` listens, and it refuses every address but the operator host's, verified by a probe from another host in the same VLAN, since a probe from elsewhere can be stopped by OPNsense instead and prove nothing.
- [x] Each job's credential files are readable only by its own user, verified in the role's Molecule verify.
- [x] Unit tests for the poll, decide and run step assert it acts on `origin/main` only and records a commit as deployed only after its run succeeds.
- [x] The role converges idempotently.

## Open items

- Token lifetime is a project decision ([ADR 0044 (CD agent trigger)](../decisions/0044-prod-automation-trigger-and-execution/revision-000-c.md)).
- The agent VM goes in VLAN 30, the 3XX range, next to the operator host, with 2 to 4 GB of RAM, built after VM 401's retirement frees memory. It is VM 303, `192.168.30.3`. The coding-agent host keeps no path to it ([ADR 0053 (Coding-agent network reach)](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md)). Traffic between two hosts in one VLAN is switched without reaching OPNsense, so the `sshd` source restriction to the operator host is enforced on the agent itself, not at the firewall.
- The `cd_agent` role does not remove a job dropped from `cd_agent_jobs`: its user, units and directories stay.
- The OpenBao snapshot push joins the jobs on this host once `cd-agent-snapshot` exists ([`cd-agent-approles.md`](cd-agent-approles.md)); it needs a native `rclone`, not Docker, which the role installs ([`cd-agent-host.md`](../topics/deploy/cd-agent-host.md)).
- Each job's heartbeat depends on ADR 0072's mechanism ([`gatus-job-heartbeats.md`](gatus-job-heartbeats.md)), which is not built.
- The deploy, maintenance and freshness jobs cannot log in to OpenBao yet; what is missing is in [`cd-agent-approles.md`](cd-agent-approles.md)'s open items. Applying the role before that is settled starts jobs that fail on every run.
- Nothing can apply the role until [`operator-host.md`](operator-host.md)'s Stage 3 builds VM 302, because `sshd` accepts `192.168.30.2` alone.
- Whether `deploy.yaml`'s `localhost` plays run under the unit's sandbox, which makes the filesystem read-only outside the job's state directory, is not confirmed.
- The shared SSH private key across every managed host (and possibly
  the maintainer's laptop) hasn't been split into a `cd_agent`-only
  key.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
