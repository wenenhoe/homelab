---
id: PROJ-tailnet-policy-in-tofu
title: "Tailnet Policy in OpenTofu"
type: project
status: not-started
blocked: false
summary: Move the tailnet's policy from hand edits in the console to OpenTofu through the tailscale/tailscale provider, with its private values supplied at apply time, as ADR 0059 decides.
decision: ADR-0059/0
depends_on:
  - project: PROJ-tailnet-policy-baseline
    reason: the policy it codes is the explicit-grant policy that project saves, and coding the allow-all grant would put a boundary under review that is about to be replaced
allowed_paths:
  - tofu/modules/tailscale_policy/**
  - tofu/main.tf
  - tofu/variables.tf
  - tofu/versions.tf
  - tofu/providers.tf
  - tofu/.terraform.lock.hcl
  - tofu/tests/tailscale_policy.tftest.hcl
  - tofu/tests/root.tftest.hcl
  - docs/topics/infra/vm-provisioning.md
  - docs/topics/infra/network-infra.md
---

# Tailnet Policy in OpenTofu

The tailnet's policy is authored in the Tailscale admin console and has never been reviewed as code. [`tailnet-policy-baseline.md`](tailnet-policy-baseline.md) replaces its allow-all grant by hand, once. This project then moves the policy into the Tofu root module, so a change to it is a reviewed diff and a change made in the console shows up as drift. It is staged because the first stage settles the one assumption that decides whether the provider can be used as the decision describes, and the later ones add a credential, a template, and the guards against a bad apply locking out the host that applies it.

## Scope

The `tailscale/tailscale` provider pinned in the root module, an OAuth-client credential for it in Tofu's credentials file, the policy body as a template in this repository with the maintainer's email and device IPs supplied at apply time, `tailscale_acl` for the policy and `tailscale_device_subnet_routes` with auto-approvers for route approval, and the guards that keep a bad apply from cutting off the host that runs it. The topic docs then say that Tofu owns the policy and how a grant is added.

Not in scope: managing devices, auth keys or DNS through the provider (the subnet router's join key is [ADR 0097 (Tailscale node configuration)](../decisions/0097-how-a-tailscale-node-is-configured/revision-000.md)'s, and its tag and route entries are written by the baseline and carried over unchanged with the grants); the grants themselves, which [`tailnet-policy-baseline.md`](tailnet-policy-baseline.md), [`operator-host.md`](operator-host.md) and [`coding-agent-network.md`](coding-agent-network.md) decide and which this project carries over unchanged; the state backend.

## Decision

Implements [ADR 0059 (Tailnet policy)](../decisions/0059-where-the-tailnet-policy-is-defined/revision-000.md), whose trigger, [ADR 0048 (Tofu credentials)](../decisions/0048-where-tofu-credentials-live/revision-000.md) being `accepted`, is met. The revision is `working` on one assumption, the provider's signature verification, which Stage 1 resolves. Rationale is there, never here.

## Execution plan

Update at the start and end of each PR that works a stage.

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Spike the provider's signature verification | Not started | A throwaway `tofu init` against a scratch config requiring `tailscale/tailscale` shows whether it verifies the signature or skips it, the result is folded into ADR 0059's Context, and the revision can be `approved` |
| 2 | Pin the provider and take the credential | Not started | The provider is pinned and locked in the root module, its OAuth client is a sensitive variable documented in the credentials file's entry in `vm-provisioning.md`, and `tofu plan` reads the live policy with it |
| 3 | Code the policy as a template | Not started | The policy body is a template in this repository, the email and device IPs come from the credentials file, and `tofu plan` reports no change against the policy the baseline saved |
| 4 | Guard the apply | Not started | A `tofu plan` after a manual console change reports drift, a deliberately locking `tests` entry fails the apply before it saves, and a copy of the live policy is taken before each apply |
| 5 | Declare route approval | Not started | Each route the tailnet advertises is approved through `tailscale_device_subnet_routes` and auto-approvers in the policy, and `tofu plan` reports no change |
| 6 | Hand the policy over | Not started | The topic docs name Tofu as the policy's owner and how a grant is added, and no doc still describes a console hand edit as the way |

Stage status is `Not started`, `In progress`, or `Done`.

### Stage 1 — the spike

Run it outside the repository, with `TF_DATA_DIR` set outside the checkout as [`vm-provisioning.md`](../topics/infra/vm-provisioning.md#tofu-project) requires. Nothing from it is kept except what it shows. It can run before the baseline has landed, since it touches no policy.

### Stage 4 — the guards

The policy's own `tests` block is what catches a bad apply before it saves, and the console stays the independent recovery path, because the host that applies is reachable only through the policy the apply could remove. A Tofu rollback is not the recovery path.

## Acceptance criteria

- [ ] A `tofu plan` after a manual console change reports drift.
- [ ] An apply whose `tests` entry the new policy fails is refused before it saves.
- [ ] A copy of the live policy exists before every apply.
- [ ] The maintainer's email and device IPs appear nowhere in the repository.
- [ ] The apply procedure names the console as its recovery path.
- [ ] The saved policy grants what it granted before the move, and every flow in the baseline's list still works.

## Agent handoff

- **Allowed to change:** `allowed_paths` in the frontmatter, enforced.
- **Must not change:** the linked revision's Decision; any grant the policy holds; the Proxmox, OPNsense and Ubuntu modules; the credentials file's existing entries.
- **Relevant files and interfaces:** `tofu/versions.tf` and `tofu/providers.tf` for how the Proxmox provider is pinned and configured, `tofu/tests/root.tftest.hcl` for how the root module's tests mock a provider, and the `tofu-checks` job in [`pipeline.md`](../topics/engineering/ci/pipeline.md), which needs no state or credentials.
- **Required checks:** `pre-commit run --all-files`, and `tofu fmt -check -recursive`, `tofu validate` and `tofu test` in `tofu/`.

## Risks

- A bad apply can lock out the operator host, and a Tofu rollback does not undo it. The `tests` block and the console are the guards.
- The credentials file gains a credential that can rewrite the tailnet's isolation boundary. The file stays `0600` in a `0700` directory, owned by the operator account.
- The policy changes hands twice: from the console to the baseline's edit, and then to this project. A grant that [`operator-host.md`](operator-host.md) or [`coding-agent-network.md`](coding-agent-network.md) adds by hand before Stage 3 has to be in the live policy the template is checked against.

## Open items

- How the OAuth client's expiry is tracked, since [ADR 0015 (Cloud credential expiry)](../decisions/0015-cloud-credential-expiry/revision-000.md) expects every credential to expire and something to notice, ADR 0059 expects the credential to follow Tofu's credentials file, and [ADR 0048](../decisions/0048-where-tofu-credentials-live/revision-000.md) states no expiry cadence for that file.
- Whether the rendered policy, with its private values, is written to Tofu's state, and if so whether the state's existing handling is enough.

## Closing checklist

Before deleting this doc, work through the [closing checklist](README.md#closing-checklist). It is the only copy.
