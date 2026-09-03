# 0009. Adopt Ansible instead of manual per-host deployment

**Status:** Accepted

## Context

For the first week and a half of this repo, every host was configured
by hand: SSH in, run `docker compose up` directly, repeat per host.
That didn't scale as more hosts joined the fleet — there was no way to
guarantee two hosts had actually converged to the same state, and
every change meant a fresh round of manual commands typed out again on
each host, with nothing recording what had actually been run where.

## Decision

Adopt Ansible as the only way any host is configured or deployed —
playbooks and roles converge every host from what's checked into this
repo, not from whatever commands were last typed into an SSH session.

## Consequences

Every host's state is reproducible from git and re-runnable at will,
not dependent on one operator's memory of what they ran and in what
order. Adding a host is "declare it in inventory and run
`ansible-playbook`," not "remember every command already run on the
others and repeat them correctly." This is the same reproducibility
motivation behind
[ADR 0008](0008-caddy-not-nginx-proxy-manager.md)'s move away from a
UI-configured reverse proxy, applied to host configuration as a whole
— see the main [`README.md`](../../README.md)'s stated invariant that
there's no manual step on a target host beyond running
`ansible-playbook`.

The cost: every change now goes through Ansible's execution model
(inventory, `hostvars`, task ordering, idempotency) instead of directly
editing a file over SSH — more to learn upfront, in exchange for never
having to reconstruct what state a host is actually in.
