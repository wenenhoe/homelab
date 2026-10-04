---
id: PROJ-cd-agent
title: CD Agent Host
type: project
status: not-started
blocked: false
summary: A dedicated, pull-based automation host that runs deploy, maintenance, rotation, and freshness jobs.
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

Implements [ADR 0044, revision 0-c](../decisions/0044-prod-automation-trigger-and-execution/revision-000-c.md), `approved`. Candidates [000-a](../decisions/0044-prod-automation-trigger-and-execution/revision-000-a.md) and [000-b](../decisions/0044-prod-automation-trigger-and-execution/revision-000-b.md) are abandoned.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | `cd_agent` host — dedicated LAN box, fixed IP, one timer and one unprivileged user per job for deploy/maintenance/rotation/freshness | Not started | The host runs the deploy, maintenance, rotation, and freshness jobs, each as its own user from a clean checkout of `origin/main`, with only `sshd` listening |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — `cd_agent` host

A dedicated LAN host with a fixed IP, in none of `managed_hosts`,
`app_hosts`, or `patched_hosts`. One systemd timer per job; each job's
unit runs as its own unprivileged user, fetches `origin/main`
anonymously into its own state directory, checks out the commit as a
clean tree, and runs the playbook or `tools/` entry point from it. The
poll, decide and run step is `tools/` code with unit tests. The host's
only inbound service is `sshd`, accepted from the operator host alone.
See the [decision](../decisions/0044-prod-automation-trigger-and-execution/revision-000-c.md) this stage implements.

## Acceptance criteria

- [ ] Each of the deploy, maintenance, rotation, and freshness jobs runs from its own timer, as its own user, from a clean checkout of `origin/main` it fetched itself.
- [ ] Only `sshd` listens, and it refuses every address but the operator host's, verified by a probe from another host in the same VLAN, since a probe from elsewhere can be stopped by OPNsense instead and prove nothing.
- [ ] Each job's credential files are readable only by its own user, verified in the role's Molecule verify.
- [ ] Unit tests for the poll, decide and run step assert it acts on `origin/main` only and records a commit as deployed only after its run succeeds.
- [ ] The role converges idempotently.

## Open items

- Poll interval, job schedules, token lifetime, and how a failed commit is retried are project decisions ([ADR 0044](../decisions/0044-prod-automation-trigger-and-execution/revision-000-c.md)).
- The agent VM goes in VLAN 30, the 3XX range, next to the operator host, with 2 to 4 GB of RAM, built after VM 401's retirement frees memory; its VMID and address are not assigned. The coding-agent host keeps no path to it ([ADR 0053](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md)). Traffic between two hosts in one VLAN is switched without reaching OPNsense, so the `sshd` source restriction to the operator host is enforced on the agent itself, not at the firewall.
- The OpenBao snapshot push joins the jobs on this host once `cd-agent-snapshot` exists ([`cd-agent-approles.md`](cd-agent-approles.md)); it needs a native `rclone`, not Docker.
- Each job's heartbeat depends on ADR 0072's mechanism ([`gatus-job-heartbeats.md`](gatus-job-heartbeats.md)), which is not built.
- Which cloud credentials beyond B2/R2/OCI get rotation automation,
  and whether "rotation" means alert-only or full rotate-and-revoke,
  isn't scoped yet.
- The shared SSH private key across every managed host (and possibly
  the maintainer's laptop) hasn't been split into a `cd_agent`-only
  key.

## Closing checklist

Copied from [`README.md`](README.md#when-a-project-finishes); run before
deleting this doc.

- [ ] Every acceptance criterion is met, and its required check passed.
- [ ] Every bullet of the linked revision's Decision is implemented, or named by a successor project.
- [ ] The linked revision is `accepted`, another project still names it, or there is no decision to settle.
- [ ] Every resulting behavior is described in a topic doc.
- [ ] Every open item is resolved and promoted, or moved where it belongs.
- [ ] Other projects' `depends_on` entries naming this one are removed,
      and every cross-reference into this doc is updated or deleted.
