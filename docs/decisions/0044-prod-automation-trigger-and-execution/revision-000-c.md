---
id: ADR-0044
revision: 0
candidate: c
type: adr
title: Trigger and execution of prod-touching automation
solution: A pull-based CD agent that runs the repo's own playbooks and tools directly, one sandboxed systemd unit per job under its own user
summary: How deploys and rotations that touch prod are triggered and run, without GitHub dispatching a job to a prod-reaching host.
topic: deployment-platform
status: approved
related: [ADR-0020, ADR-0023, ADR-0043, ADR-0047, ADR-0050, ADR-0054, ADR-0058, ADR-0072]
---

# 0044. Trigger and execution of prod-touching automation

## Problem

How deploys and rotations that touch prod are triggered and run, without GitHub dispatching a job to a prod-reaching host.

## Context

[`revision-000-a.md`](revision-000-a.md) sets out why nothing GitHub dispatches, hosted or self-hosted, may run prod-touching work for a public repo, and why a webhook-driven engine is out: it needs an inbound endpoint. This candidate keeps both conclusions. It differs on what runs a job once a pull-based poller sees work to do.

The jobs are the ones [`cd-agent.md`](../../projects/cd-agent.md) lists: deploy (`deploy.yaml` against `managed_hosts`), maintenance (`maintenance.yaml` against `patched_hosts`), and the rotation and freshness jobs of [ADR 0023](../0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md). Each is one `ansible-playbook` or `tools/` invocation. None needs an operator: `ansible/ansible.cfg` sets `become_ask_pass = False`, and the only `pause` in the roles' tasks is in `restore`, which is not a CD job.

**What isolation buys.** A job exists to reach `managed_hosts`, OpenBao, and the cloud credentials, and the code it runs is `main`'s, which the poller trusts by design. As [`revision-000-a.md`](revision-000-a.md) observes of CI isolation, a sandbox stops mattering once the job's purpose is reaching internal infrastructure. What bounds this path is who can change `main` ([ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md)), what each job's identity can read ([ADR 0020 revision 1](../0020-automation-identity-and-access-scope/revision-001.md)), and which direction trust runs toward hosts that run untrusted code ([ADR 0054](../0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md)).

**Threat model.** The adversary can write to `main`, through the maintainer's GitHub account or push credential, or controls a managed host or the coding-agent host. The asset is every credential the CD agent holds. The attack paths are a commit on `main` the maintainer did not make, one job's code reading another job's credentials, and data from an untrusted host reaching a job that holds production credentials.

## Decision

- **Host.** A dedicated VM with a fixed address, the CD agent, that is in none of `managed_hosts`, `app_hosts`, or `patched_hosts` and is not the operator host ([ADR 0058](../0058-where-operator-work-runs/revision-000.md)). The coding-agent host has no network path to it ([ADR 0053](../0053-network-reach-of-the-coding-agent-host/revision-000.md)). Nothing that triggers or serves a job listens. The one inbound service is `sshd`, accepted from the operator host's address alone, for provisioning and break-glass; [`revision-000-a.md`](revision-000-a.md) says zero inbound ports with no exception, yet its provisioning guard presumes SSH. Job traffic is all outbound: `git fetch` from GitHub, SSH to managed hosts, OpenBao's API, the cloud providers' APIs, and Telegram.
- **Trigger.** One systemd timer per job. The deploy job polls every few minutes: it fetches `origin/main` over anonymous HTTPS and acts only when the fetched commit differs from the last one it deployed successfully. Maintenance, rotation, and freshness run on their own schedules against the latest fetched `origin/main`. Nothing GitHub sends can start a job: no webhook, no dispatched workflow, no runner registered with GitHub.
- **Execution.** A job's unit fetches into its own state directory, checks out the exact commit as a clean tree, and runs the playbook or tool from that tree directly. No execution engine sits between the poller and Ansible. A lock allows one run of a job at a time, and a commit counts as deployed only after its run succeeds. The poll, decide and run step is repo code under `tools/` with unit tests ([ADR 0064](../0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md)), not shell in a unit file.
- **Identity per job.** Each job runs as its own unprivileged user in a sandboxed systemd unit, and its credentials (its OpenBao AppRole `secret_id`, its SSH key) are readable only by that user. [ADR 0020 revision 1](../0020-automation-identity-and-access-scope/revision-001.md) separates the deploy and rotation roles by policy alone, since both would share a host; this adds an operating-system boundary under that policy. The management job that [ADR 0054](../0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md) requires for an untrusted host is one more such user, holding only that host's key.
- **Commits.** The agent trusts `origin/main` as GitHub serves it and verifies no signatures. [ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md) leaves commit provenance to this decision; the boundary is who can push to `main`, which is the push credential held only on the maintainer's laptop ([ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md)) and the GitHub account behind it.
- **Self-protection.** The CD agent never provisions itself and no deploy play targets it. The operator host applies its configuration, and the provisioning playbook refuses to run when the machine it runs on is the CD agent, comparing machine identity rather than hostname or address, which also catches an SSH loopback to itself.

## Alternatives considered

- **A poller driving `preloop` microVMs ([`revision-000-a.md`](revision-000-a.md)).** The jobs gain no containment that matters (see Context). The costs are real on this node. `smolvm`, its microVM layer, [requires `/dev/kvm`](https://github.com/smol-machines/smolvm), which a Proxmox guest has only with nested virtualization. `preloop`'s [CLI reference](https://github.com/preloopdev/preloop/blob/main/docs/cli_reference.md) puts the official golden image at about 60 GB on disk and defaults each runner to 8 vCPUs, and `preloop run` starts a resident engine with its own state and secret store beside the OpenBao AppRoles. It is a pre-1.0 project (v0.33.x releases) whose control plane is source-available under FSL-1.1-MIT. The same reference names `push`, `pull_request` and `merge_group` as simulated events and does not say how `schedule` or `workflow_dispatch` behave, so that candidate's first assumption is not settled by reading. The one benefit left, a shared workflow format with CI, carries no weight: the CD jobs are single playbook or tool invocations and `pr-checks.yml` runs on GitHub-hosted runners. That candidate also re-ran the repo's pre-push CI on the agent host. The repo's pre-push stage is `pre-commit` hooks that run on the laptop ([ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md)), and running unmerged code on a host that holds production credentials is a path this design does not open.
- **A private Gitea or Forgejo with Actions ([`revision-000-b.md`](revision-000-b.md)).** It adds a forge with a web UI, a database, accounts, and its own patch and backup cadence, plus a LAN listener for the instance and the runner's registration, to do what a timer and `git fetch` do. Mirror latency needs the 10-minute floor or an on-demand sync call, its dispatch safety lasts only while one account exists, and three of its assumptions each need a spike.
- **Verifying signed commits on the agent.** It would take GitHub and the push credential out of the trust boundary for what the agent runs. It needs a signing key on the laptop, which [ADR 0056](../0056-credentials-held-by-the-maintainer-workstation/revision-000.md) does not list among the credentials the laptop holds, so it revises that decision as much as this one.
- **One user and one unit for every job.** The rotation job's credentials, which include master-tier cloud credentials, would be readable by the deploy job, whose code reaches every managed host. Rejected: it discards the separation [ADR 0020 revision 1](../0020-automation-identity-and-access-scope/revision-001.md) draws between the two.

## Consequences

- Jobs run with the authority of whoever can push to `main`. A compromised GitHub account or push credential reaches every host the agent reaches. This residual risk is accepted; [ADR 0050](../0050-agent-authored-changes-reaching-production/revision-000.md)'s review step and the laptop's credential limits are what shrink it.
- Per-user separation and unit sandboxing protect against a compromised job process, not against root on the agent host, which can read every job's credentials.
- A sealed OpenBao makes every job that reads it fail and alert until it is unsealed by hand ([ADR 0018](../0018-unsealing-the-secrets-store-after-restart/revision-000.md)).
- A stopped poller is the failure an `OnFailure` hook cannot report, so each job also sends a heartbeat as [ADR 0072](../0072-detecting-scheduled-jobs-that-stop-running/revision-000.md) defines.
- The AppRoles' CIDR bind ([ADR 0020 revision 1](../0020-automation-identity-and-access-scope/revision-001.md)) holds directly: jobs run on the agent host itself, so every login arrives from its fixed address.
- Poll interval, schedules, token lifetime, and how a failed commit is retried are project decisions ([`cd-agent.md`](../../projects/cd-agent.md)). The host needs no hardware virtualization and its sizing is a project decision too.

## Invariants

- Nothing GitHub sends can start a job, and no listener triggers or serves one.
- A job runs only the tree of a commit it fetched from `origin/main` itself: never a branch, a fork, a pull request, or an edited working tree.
- No job's user can read another job's credentials.
- The CD agent holds no credential that can write to the GitHub remote.
- The CD agent never provisions itself.

## Non-goals

- What each AppRole may read ([ADR 0020 revision 1](../0020-automation-identity-and-access-scope/revision-001.md)).
- How the agent's first credential arrives ([ADR 0047](../0047-first-credential-bootstrap-for-automated-processes/revision-000.md)).
- The host's OS hardening baseline ([ADR 0043](../0043-host-os-hardening-baseline/revision-000.md)), which it inherits.
- Tofu and break-glass access ([ADR 0058](../0058-where-operator-work-runs/revision-000.md)).
- Splitting the shared SSH key, tracked in [`cd-agent.md`](../../projects/cd-agent.md).
- Verifying commit signatures (see Alternatives considered).

## Validation

A probe from another host lists the agent's listening ports and fails on any beyond `sshd`, and confirms `sshd` refuses every address but the operator host's. The role's Molecule verify checks that each job's credential files are readable only by that job's user. Unit tests for the poll, decide and run step assert that it acts on `origin/main` only and records a commit as deployed only after its run succeeds.

## Reconsideration triggers

- A second account gains push access to `main`, or the residual risk of a compromised GitHub account is judged unacceptable: revisit signed-commit verification.
- A job needs to run code or input that is not `main`'s: revisit an isolating execution engine ([`revision-000-a.md`](revision-000-a.md)).
- A job must start sooner after a push than the poll interval allows.
