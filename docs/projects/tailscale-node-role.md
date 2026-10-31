---
id: PROJ-tailscale-node-role
title: "Tailscale Node Role"
type: project
status: building
blocked: false
summary: Write the Ansible role that installs, joins and configures a Tailscale node, prove it against the live subnet router with no change, and hand the rebuild of VM 202 a tagged join.
decision: ADR-0097/0
allowed_paths:
  - ansible/roles/tailscale_node/**
  - ansible/playbooks/network-infra.yaml
  - ansible/inventory/inventory.yaml
  - ansible/inventory/host_vars/tailscale.yaml
  - ansible/molecule-coverage/thresholds.yaml
  - docs/topics/deploy/ansible.md
  - docs/topics/infra/network-infra.md
  - docs/topics/engineering/molecule-testing.md
---

# Tailscale Node Role

Nothing in the repository configures a Tailscale node, so the rebuild of VM 202 in [`tofu-migration.md`](tofu-migration.md) has nothing to rebuild it from. This project writes the role, shows it reproduces the live router, and proves the tagged join, so the rebuild is one more run of the cycle that migration already describes. It is staged because the first stage settles the assumption that decides the role's shape, and the last needs the tailnet's policy to carry the router's tag.

## Scope

The `tailscale_node` role and the play that applies it to the `network_infra` group, its Molecule scenario, the host variable that lists the routes a node advertises, and the topic doc's description of the result. Not in scope: the tailnet's policy ([`tailnet-policy-baseline.md`](tailnet-policy-baseline.md) writes the router's tag, `tagOwners` and `autoApprovers`; [`tailnet-policy-in-tofu.md`](tailnet-policy-in-tofu.md) moves the policy into Tofu), the rebuild of VM 202 itself ([`tofu-migration.md`](tofu-migration.md)), and the GCP node ([`off-site-monitoring.md`](off-site-monitoring.md)).

## Decision

Implements [ADR 0097 (Tailscale node configuration)](../decisions/0097-how-a-tailscale-node-is-configured/revision-000.md). The revision is `working` on one assumption, which Stage 1 resolves. Rationale is there, never here.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike `tailscale set` on a logged-in scratch node | Done | On a scratch node joined with a one-time key, `tailscale set` changes the advertised routes, the DNS setting and auto-update with no key, the values survive a restart of `tailscaled` and of the VM, and the result is folded into ADR 0097's Context so the revision can be `approved` |
| 2 | Write the role and show it matches the live router | In progress | The role's Molecule scenario passes with its idempotence check, and the role run against the existing VM 202 reports two changes under `--check`, the replacement of the vendor's one-line apt source and the client's auto-update turned off, and no change on the run after a real one |
| 3 | Prove the tagged join | Not started | After the baseline's saved policy carries the router's tag, a scratch node joined by the role with a one-time tagged key has its route approved without the console, reports no key expiry, and a second run reports no change |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — the spike

Run it outside the repository, on a scratch Tofu VM joined with a one-time key made by hand, with no tag, so it needs nothing from the policy. Remove the device from the tailnet afterwards. Nothing from it is kept except what it shows.

### Stage 2 — parity with VM 202

The role's variables are the preferences read off the router: the advertised route and the DNS setting. The client's updater is not a variable, because the decision turns it off on every node. Running it against the live node before any rebuild is the check that the role describes what is there. Two differences are expected: the node has the vendor script's one-line apt source, which the role replaces with its own, and the node's client auto-update is on, which the role turns off. The router is the tailnet's route into the lab, so the first run is `--check`, and a diff it reports is read before a real run.

### Stage 3 — the join

The stage waits on the baseline's Stage 2, which adds the tag and its entries. It does not wait on the policy moving into Tofu.

## Acceptance criteria

- [ ] The role installs Tailscale, sets forwarding, joins a logged-out node with a one-time tagged key, and converges the node's preferences, and a second run reports no change.
- [ ] A logged-out node with no key stops the play before anything changes, and a logged-in node needs no key.
- [ ] No auth key appears in the repository, in a log or on disk after the run.
- [ ] The role run against VM 202 changes only its apt source and its client auto-update preference, and a second run reports no change.
- [ ] VM 202, rebuilt by [`tofu-migration.md`](tofu-migration.md), carries its tag, has its route approved without the console and has no key expiry.
- [ ] [`network-infra.md`](../topics/infra/network-infra.md) describes the node's configuration and how a route is added, and the scenario is in [`molecule-testing.md`](../topics/engineering/molecule-testing.md)'s matrix.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the linked revision's Decision; the tailnet's policy; the Tofu root module; the `tailscale` host's address, user or group membership beyond what the generated inventory later replaces.
- **Relevant files and interfaces:** [`network-infra.md`](../topics/infra/network-infra.md) for the host's recorded state, the `docker` role's apt repository tasks as the model for the install, and the `qemu_guest_agent` role's scenario as the model for a role that runs on `network_infra`.
- **Required checks:** `pre-commit run --all-files`, the role's Molecule scenario, and `ansible-lint` by hand.

## Risks

- VM 202 is the route into the lab away from home, so a real run against it is made from inside the network, with the Proxmox console as the way back.
- The join cannot be run in Molecule, so Stage 3 is the only test of it, and a flaw in it shows during the rebuild if Stage 3 is skipped.
- The policy changes hands before this project's Stage 3 and again later. The router's tag and its entries are carried over unchanged, and a route added by hand in between has to be in the saved policy the Tofu template is checked against.

## Open items

- Whether the GCP node joins the tailnet as a node, which would make it a second user of this role.
- How the one-time key reaches the play on the operator host, settled with the role's variables in Stage 2.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
