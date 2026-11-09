---
id: EXP-host-drift-detection
title: "How could the lab notice that a host no longer matches what `main` declares?"
type: exploration
status: open
summary: "Whether a scheduled job can report a host that differs from `main`, given that `deploy.yaml` does not run in check mode, and what such a job may touch."
topic: deployment-platform
related: [ADR-0044, ADR-0072, ADR-0102]
---

# How could the lab notice that a host no longer matches what `main` declares?

A host differs from `main` when something was changed on it by hand, or when a
deploy that should have converged it did not. Today the difference shows only
through its effect. The question is whether a scheduled job can report it with a
verdict that means something, and what that job would be allowed to change.

## What bears on it

- The CD agent's `deploy` job runs `deploy.yaml` when `main` holds a commit it has
  not deployed, and its other jobs run on calendars
  ([`cd-agent-host.md`](../topics/deploy/cd-agent-host.md)). No job compares a host
  with `main` between commits. A hand change to something a role manages stays
  until a deploy next converges it, and nothing records that it was there.
- `deploy.yaml --check` does not work. `ensure_vault_secret` generates a secret
  when a read finds nothing and declares no check-mode support
  (`ansible/roles/secrets/library/ensure_vault_secret.py`), and
  [`network-infra.md`](../topics/infra/network-infra.md) records that `--check`
  puts the secrets play in check mode, which fails.
- Some plays already report change without applying it. Tailscale takes
  `-e network_infra_check=true`, a flag of its own because `--check` fails on the
  secrets play. The OPNsense gateway takes `--check --diff`, and a forward the role
  does not write "reports as a change"
  ([`opnsense-gateway.md`](../topics/infra/tofu/opnsense-gateway.md)).
  `cleanup.yaml` takes `--check --diff` too ([`cleanup.md`](../topics/deploy/cleanup.md)).
- The `compose`, `caddy`, `backup_agent` and `bind9` roles use modules and no
  `command` or `shell` tasks, so most of the deploy path can report change in
  check mode. `community.docker.docker_container_exec` tasks appear throughout the
  roles, and how they behave in check mode has not been checked.
- Without `--on-change` a CD agent job runs the latest fetched `main` and records
  nothing ([`cd-agent-runner.md`](../topics/deploy/cd-agent-runner.md)). A job's
  heartbeat is pushed on success only, so a failed or missing run is what Gatus
  alerts on ([`gatus.md`](../topics/monitoring/gatus.md#pushing-from-a-job)). A
  drift verdict would therefore be the job failing, not data the job carries.
- OpenTofu is a separate question.
  [`tofu-plan-guard.md`](../projects/tofu-plan-guard.md) leaves a plan job on the
  CD agent out of its scope, as its own decision.

Still to find out:

- What `deploy.yaml` reports in check mode on a host that has just been converged.
  A run that reports change with nothing drifted makes the verdict noise.
- How the `docker_container_exec` tasks behave in check mode, and which tasks
  cannot preview at all and would hide drift without saying so.
- Which Vault identity a check run would use, and what it would read.

## Options

1. **Check mode of `deploy.yaml`, with the secrets play kept out of it**, the shape
   of `network_infra_check`. It reports the changed tasks of the real playbook.
   Cost: the secrets play has to run for real or gain a read-only mode, since it
   creates a secret when none exists and a check run should create nothing. Tasks
   that always report change make the verdict noisy.
2. **A scheduled run of `deploy.yaml` with no new-commit gate**, read for its change
   count. It detects and repairs in one run. Cost: it applies changes and can
   restart services outside a promotion, a hand change is overwritten before anyone
   sees it, and the runner or the playbook has to turn a change count into a
   failure.
3. **Narrow checks per kind of drift**, such as a running container's image digest
   against its declared pin or a rendered file against its template. Cost: new
   tooling for each kind, and coverage is only what was written. It needs no check
   mode.
4. **Nothing beyond the deploy on each new commit.** Cost: a hand change or a
   half-converged host goes unnoticed until its effect shows, and nothing says for
   how long.

## Leaning

Find the first fact before choosing: run `deploy.yaml` in check mode, with the secrets
play handled as Tailscale's is, against one converged host and read what it reports.
Few changes make option 1 cheap. A long list of changes with nothing drifted makes
option 3, or a narrower option 1, the realistic path.
