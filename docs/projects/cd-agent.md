---
id: PROJ-cd-agent
title: CD Agent Host and Credentials
type: project
status: building
blocked: false
summary: A dedicated, pull-based automation host that runs the deploy, maintenance, and credential-expiry jobs, with the CIDR-bound AppRoles it logs in with and the delivery and rotation of each job's credentials.
decision: ADR-0044/0-c
also_implements:
  - ADR-0043/0
  - ADR-0020/1
  - ADR-0022/1
super_project: pull-based-cd
depends_on:
  - project: PROJ-operator-host
    reason: Nothing can apply the role until VM 302 exists, because `sshd` accepts the operator host's address alone
allowed_paths:
  - ansible/roles/cd_agent/**
  - ansible/filter_plugins/cd_agent_chain.py
  - ansible/playbooks/cd-agent.yaml
  - ansible/inventory/inventory.yaml
  - ansible/inventory/group_vars/cd_agent.yaml
  - ansible/inventory/group_vars/all/main.yaml
  - ansible/inventory/group_vars/all/secret_catalog.yaml
  - ansible/molecule-coverage/thresholds.yaml
  - ansible/tests/test_cd_agent_*.py
  - tools/cd_agent/**
  - tools/tests/cd_agent/**
  - tools/cloud_credentials/systemd/**
  - tools/cloud_credentials/rotate_leaf_keys.py
  - tools/tests/cloud_credentials/test_rotate_leaf_keys.py
  - docs/topics/deploy/cd-agent-host.md
  - docs/topics/deploy/cd-agent-runner.md
  - docs/topics/infra/host-hardening.md
  - docs/topics/secrets/cloud-credentials/rotation.md
  - docker/openbao/policies/cd-agent-*.hcl
  - docker/openbao/policies/vault-bootstrap.hcl
  - ansible/roles/secrets/**
  - tools/utils/repo.py
  - tools/tests/utils/**
  - tools/cloud_credentials/**
  - tools/tests/cloud_credentials/**
  - docs/topics/secrets/openbao-cd-agent-approles.md
---

# CD Agent Host and Credentials

Replaces manual `ansible-playbook` deploys and rotation runs with a
dedicated, pull-based automation host. The second half of the
OpenBao+CD-agent migration this repo originally scoped together —
OpenBao itself is done; see ADRs
[0111](../decisions/0111-recovering-the-secrets-store-from-total-loss/revision-000.md) and 0018 through
[0026](../decisions/0026-detecting-reads-of-high-value-secrets/revision-000.md)
and the `openbao-*.md` docs for that half.

This is the first of two projects in the `pull-based-cd` initiative; [`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md) retires `controller`'s standing AppRole once the agent runs the jobs. The host and its AppRoles are one project because the host cannot run a job before its credentials are delivered, and the credentials are delivered to a host that exists.

## Scope

The `cd_agent` host: a dedicated LAN box with a fixed IP and no job-serving listener (SSH from the operator host only), running the jobs that replace manual `ansible-playbook` deploys and rotation runs. Also the four AppRoles `cd-agent-deploy`, `cd-agent-rotation`, `cd-agent-credential-expiry` and `cd-agent-snapshot`, their policies, and their CIDR binding; a command run from the operator host that delivers one job's credential files to `cd_agent`; the rotation of a job's `secret_id` using the same command; and the check that the `credential-expiry` job's heartbeat arrives on success only. Not in scope: retiring `controller`'s standing AppRole ([`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md)).

Not in: the rest of `tools/` beyond the paths in `allowed_paths`; the `tools/` named in this doc means the job entry points and `cd_agent`, `cloud_credentials` and `utils`.

## Decision

Implements [ADR 0044 revision 0-c (CD agent trigger)](../decisions/0044-prod-automation-trigger-and-execution/revision-000-c.md), `approved`. Candidates [000-a](../decisions/0044-prod-automation-trigger-and-execution/revision-000-a.md) and [000-b](../decisions/0044-prod-automation-trigger-and-execution/revision-000-b.md) are abandoned.

It also implements [ADR 0020 revision 001 (Automation identity scope)](../decisions/0020-automation-identity-and-access-scope/revision-001.md), `approved`, and [ADR 0022 revision 1 (Controller TLS trust)](../decisions/0022-controller-trust-in-the-secrets-store-tls/revision-001.md), which are set `accepted` in the pull request that closes the project.

It carries out the `secret_id` handoff of
[ADR 0047 (First-credential bootstrap)](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md),
`approved`: a response-wrapped value requested through `vault-bootstrap`,
carried on SSH stdin and unwrapped once on `cd_agent`. The wrapping call
needs the `vault-bootstrap` AppRole's `secret_id`, typed at a hidden prompt,
so the command is run by a person and is not unattended.
[`cd-agent-controller-approle-retirement.md`](cd-agent-controller-approle-retirement.md) names that revision, so it stays `approved` when this project closes. How
ADR 0020 revision 1 leaves the rotation cadence to a project is settled in Stage 6.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | The runner and the `cd_agent` role: the poll, decide and run step, the users, units and `sshd` restriction built from `cd_agent_jobs`, the inventory group and `playbooks/cd-agent.yaml` | Done | The unit tests for the poll, decide and run step pass, the role converges idempotently, and each job's credential files are readable only by its own user in the role's Molecule verify |
| 2 | `cd-agent-deploy` / `cd-agent-rotation` / `cd-agent-credential-expiry` / `cd-agent-snapshot` AppRoles, CIDR-bound | In progress | both roles exist with the policies in ADR 0020 revision 001, each bound to `cd_agent`'s fixed IP |
| 3 | Jobs read their credential where it is delivered | In progress | a job's unit names its credentials directory, and `tools/` and the `secrets` role log in to OpenBao and resolve `main-domain` from it |
| 4 | Jobs verify OpenBao against a delivered root cert | In progress | `tools/` uses a `step-ca-root.crt` delivered to the credentials directory, and the `secrets` role fails when a delivered copy differs from the root it just fetched |
| 5 | The host: VM 303 in VLAN 30 with the role applied, and the `credential-expiry` heartbeat endpoint declared | Not started | VM 303 runs the role with only `sshd` listening, and its effective apt configuration passes the checks in `host-hardening.md` |
| 6 | Deliver and rotate a job's credentials | Not started | one command writes a job's `openbao-controller-secret-id`, `openbao-controller-role-id`, `main-domain` and `step-ca-root.crt` into its credentials directory with the owner and modes the job expects; the deploy, maintenance and credential-expiry jobs each log in and run as their own user from a clean checkout of `origin/main`; and the same command adds a new `secret_id`, confirms a login with it and destroys the old one by its accessor, with no failed job run in between |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — `cd_agent` host

A dedicated LAN host with a fixed IP, in none of `managed_hosts`,
`app_hosts`, or `patched_hosts`. One systemd timer per job; each job's
unit runs as its own unprivileged user, fetches `origin/main`
anonymously into its own state directory, checks out the commit as a
clean tree, and runs the playbook or `tools/` entry point from it. The
poll, decide and run step is [`tools/cd_agent/run_job.py`](../../tools/cd_agent/run_job.py), unit-tested and described in [`cd-agent-runner.md`](../topics/deploy/cd-agent-runner.md). The host's
only inbound service is `sshd`, accepted from the operator host alone. The `cd_agent` role ([`cd-agent-host.md`](../topics/deploy/cd-agent-host.md)) builds the users, units and `sshd` restriction from a `cd_agent_jobs` list. The `cd_agent` inventory group, the jobs' definitions in its group variables and `playbooks/cd-agent.yaml` apply it. Rotation is [`cd-agent-job-ssh-keys.md`](cd-agent-job-ssh-keys.md)'s.
The `credential-expiry` job replaces the weekly user timer on `controller` (`tools/cloud_credentials/systemd/`), running as a plain weekly timer on this always-on host. See the [decision](../decisions/0044-prod-automation-trigger-and-execution/revision-000-c.md) this project implements.

### Stage 2 — AppRoles

Four CIDR-bound AppRoles, per the
[decision](../decisions/0020-automation-identity-and-access-scope/revision-001.md):
`cd-agent-deploy` (read on `hosts/*` and `cloud_credentials/leaf/*`,
`create` but not `update` on `hosts/*`), `cd-agent-rotation`
(create/update on both `cloud_credentials/leaf/*` and
`cloud_credentials/rotation/*`, nothing under `hosts/*`) and
`cd-agent-credential-expiry` (read-only on `cloud_credentials/leaf/*`,
`cloud_credentials/rotation/*` and `hosts/all/telegram/*`) and
`cd-agent-snapshot` (read on `sys/storage/raft/snapshot` and six named
snapshot-push leaf paths) — a compromised deploy run shouldn't be able
to reach rotation-tier credentials, the credential expiry check shouldn't be able
to write any, and the snapshot job shouldn't be able to read any other
leaf.

The four policies and the role-creation runbook are in
[`openbao-cd-agent-approles.md`](../topics/secrets/openbao-cd-agent-approles.md).
What remains needs the running host: creating the roles with `cd_agent`'s fixed
address (`192.168.30.3`) as both CIDR binds. Delivering each job's files, and
the `secret_id` rotation cadence, are Stage 6.

### Stage 3 — Credential location

A CD agent job's clean checkout has no `ansible/files/secrets/`, where the
`secrets` role and `tools/utils/repo.py` read `main-domain` and the
controller AppRole's `role_id` and `secret_id`. `HOMELAB_SECRETS_DIR`, an
absolute path set in the job's unit to its credentials directory
(`/etc/cd-agent/credentials/<job>/`), moves that cache; unset, it stays in
the checkout, so operator runs are unchanged. The delivered files keep the
names the readers already use: `main-domain`, `openbao-controller-role-id`
and `openbao-controller-secret-id`. See
[`openbao-cd-agent-approles.md`](../topics/secrets/openbao-cd-agent-approles.md).

### Stage 4 — Root cert trust

A job has no SSH key to `security`, so it cannot fetch step-ca's root cert
as [revision 0](../decisions/0022-controller-trust-in-the-secrets-store-tls/revision-000.md)
does. [Revision 1](../decisions/0022-controller-trust-in-the-secrets-store-tls/revision-001.md)
has the root, which is public, delivered to each job's credentials directory
as `step-ca-root.crt`. `cloud_credentials` uses it when it exists, and a run of
the `secrets` role that has both that file and a freshly fetched root fails
when they differ. The project's `also_implements:` names that revision, which
is set `accepted` in the PR that closes the project.

### Stage 5 — The host

VM 303 in VLAN 30, `192.168.30.3`, with the role applied and `sshd` accepted from the operator host alone. The `credential-expiry` heartbeat endpoint is declared with the host (see Open items). The role cannot be applied until [`operator-host.md`](operator-host.md) builds VM 302.

### Stage 6 — Delivery and rotation

For one job: request a wrapped `secret_id` for its AppRole, send the
wrapping token to `cd_agent` over SSH stdin, unwrap it there into the job's
`0400` file, and write the other three files, which are not secret, beside
it. A job's second `secret_id`, such as `cd-agent-deploy`'s for
`redeploy-storage` ([ADR 0074 (Job chaining)](../decisions/0074-following-one-automation-job-with-another-under-a-different-identity/revision-000.md)),
is the same command for another job's directory. The files and their names
are in
[`openbao-cd-agent-approles.md`](../topics/secrets/openbao-cd-agent-approles.md).

An AppRole holds several `secret_id`s at once, so a rotation adds the new one,
confirms a login with it, then destroys the old one by its accessor.
Rotate when `cd_agent` is rebuilt or re-provisioned, when the operator host's
credentials change, on any suspected exposure, and every 90 days. The
`secret_id` has no expiry of its own, so a missed rotation is not an outage.

## Acceptance criteria

- [ ] Each of the deploy, maintenance, and credential-expiry jobs runs from its own timer, as its own user, from a clean checkout of `origin/main` it fetched itself.
- [ ] Only `sshd` listens, and it refuses every address but the operator host's, verified by a probe from another host in the same VLAN, since a probe from elsewhere can be stopped by OPNsense instead and prove nothing.
- [x] Each job's credential files are readable only by its own user, verified in the role's Molecule verify.
- [x] Unit tests for the poll, decide and run step assert it acts on `origin/main` only and records a commit as deployed only after its run succeeds.
- [x] The role converges idempotently.
- [ ] The host's effective apt configuration passes the checks in [`host-hardening.md`](../topics/infra/host-hardening.md#verifying-a-host); the last project to close that names [ADR 0043 (Host hardening baseline)](../decisions/0043-host-os-hardening-baseline/revision-000.md) sets it `accepted`.
- [ ] All four AppRoles exist with the policies in ADR 0020 revision 001.
- [ ] Each is bound to `cd_agent`'s fixed IP (`secret_id_bound_cidrs` and `token_bound_cidrs`).
- [ ] `cd-agent-deploy` cannot read `cloud_credentials/rotation/*`, verified.
- [ ] `cd-agent-deploy` can create a missing `hosts/*` path and cannot update an existing one, verified.
- [ ] `cd-agent-rotation` can read no `hosts/*` path, verified.
- [ ] `cd-agent-credential-expiry` can read the leaf, rotation and Telegram paths and write none of them, verified.
- [ ] `cd-agent-snapshot` can save a snapshot and read its six named leaf paths, and can read no other leaf path, verified.
- [ ] A job's unit sets `HOMELAB_SECRETS_DIR` to its credentials directory, verified.
- [ ] With it set, `tools/` and the `secrets` role log in and resolve `main-domain` from that directory and not from the checkout, and a relative value is refused, verified.
- [ ] With `step-ca-root.crt` in the credentials directory, `cloud_credentials` verifies OpenBao against it and does not fetch from `security`, and a file that is not a certificate is refused, verified.
- [ ] A `secrets` role run that has a delivered copy equal to the fetched root passes, one with a different copy fails naming the file, and one with no copy is unchanged, verified.
- [ ] One command delivers a job's four files, each with the owner and mode the job needs, and a job started afterwards logs in to OpenBao, verified.
- [ ] Each `secret_id` is delivered response-wrapped over stdin and unwrapped once on `cd_agent` into the job user's `0400` file, the wrapping token never appears in a process argument or a log, and a second unwrap of it fails, verified.
- [ ] A rotation leaves exactly one valid `secret_id` for that job and no failed run, verified.
- [ ] A step-ca root change is covered by re-running delivery for every job, and the deploy-side check then passes, verified.
- [ ] The rotation cadence and its triggers are in a topic doc.
- [ ] The `credential-expiry` job pushes to its Gatus endpoint on success only, so a run that fails, including one that cannot log in to OpenBao, alerts as a missed heartbeat without needing OpenBao to send it, verified on the host.

## Risks

- A wrapping token has a short lifetime, so a delivery that stalls between the wrap and the unwrap has to be repeated.
- A wrong file name or mode breaks a job on its next run, so the command verifies each file before it reports success.

## Open items

- Token lifetime is a project decision ([ADR 0044 (CD agent trigger)](../decisions/0044-prod-automation-trigger-and-execution/revision-000-c.md)).
- The agent VM goes in VLAN 30, the 3XX range, next to the operator host, with 2 to 4 GB of RAM, built after VM 401's retirement frees memory. It is VM 303, `192.168.30.3`. The coding-agent host keeps no path to it ([ADR 0053 (Coding-agent network reach)](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md)). Traffic between two hosts in one VLAN is switched without reaching OPNsense, so the `sshd` source restriction to the operator host is enforced on the agent itself, not at the firewall.
- The `cd_agent` role does not remove a job dropped from `cd_agent_jobs`: its user, units and directories stay.
- The OpenBao snapshot push joins the jobs on this host once `cd-agent-snapshot` exists (Stage 2); it needs a native `rclone`, not Docker, which the role installs ([`cd-agent-host.md`](../topics/deploy/cd-agent-host.md)).
- Each job's heartbeat uses ADR 0072's mechanism, which is built ([ADR 0072 (Job heartbeats)](../decisions/0072-detecting-scheduled-jobs-that-stop-running/revision-000.md)). The `credential-expiry` job's endpoint is not declared, because one nothing pushes to alerts once its interval passes; add it with the host, as [`cd-agent-host.md`](../topics/deploy/cd-agent-host.md#heartbeats) lists. That edit touches `main.yaml`, the secret catalog and `cd_agent.yaml`, which this project's `allowed_paths` must then name.
- The deploy, maintenance and credential-expiry jobs cannot log in to OpenBao yet; what is missing is delivering each job's credentials, which Stage 6 does. Applying the role before that is settled starts jobs that fail on every run.
- The role cannot be applied until [`operator-host.md`](operator-host.md) builds VM 302, because `sshd` accepts `192.168.30.2` alone.
- Whether `deploy.yaml`'s `localhost` plays run under the unit's sandbox, which makes the filesystem read-only outside the job's state directory, is not confirmed.
- The OpenBao snapshot write keys are rotated by hand with `create_snapshot_write_keys.py --rotate`: the `rotation` job runs `rotate_leaf_keys.py`, which does not include them, and the expiry check only warns. Adding them is a small change to that script and `rotation.md`. The `cd-agent-rotation` policy already grants write on the whole leaf tier, and `snapshot-push.sh` reads the keys from OpenBao on every run, so a rotation needs no redeploy. Do it when the `rotation` job goes live, so its first run exercises it; this project's `allowed_paths`, if it gains any, must then name both files.
- The shared SSH private key across every managed host (and possibly
  the maintainer's laptop) is split per job by
  [`cd-agent-job-ssh-keys.md`](cd-agent-job-ssh-keys.md).
- The `credential-expiry` job's Gatus push token is a file the host needs besides the four credential files, written by hand today ([`cd-agent-host.md`](../topics/deploy/cd-agent-host.md#heartbeats)). Whether the delivery command also writes it is not decided.
- What reminds the maintainer that a 90-day rotation is due is not decided. The `credential-expiry` job cannot read the `secret_id`'s age, since its policy grants no `auth/approle` capability.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
