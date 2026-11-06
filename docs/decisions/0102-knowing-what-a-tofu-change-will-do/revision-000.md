---
id: ADR-0102
revision: 0
type: adr
title: Knowing what a Tofu change will do before it runs
short: Tofu change review
solution: A guard that checks a saved plan against a committed allow-list of destructive actions and applies that same plan, with the plan read on the operator host before merge and a credential-free address check on the pull request
summary: How a change to the OpenTofu configuration is reviewed as what it will create, replace or destroy and not only as the code that was edited, so a destroy of a resource that matters cannot pass unnoticed.
topic: deployment-platform
status: working
related: [ADR-0044, ADR-0048, ADR-0050, ADR-0058, ADR-0076]
---

# 0102. Knowing what a Tofu change will do before it runs

## Problem

A pull request that edits OpenTofu configuration shows the lines that changed. It does
not show which resources the next apply will create, replace or destroy, and a small edit
can destroy a machine or a datastore. What has to be true: before an apply, the
maintainer sees every destroy and replace of a resource that matters, a destroy nobody
named stops the apply, and what was checked is what runs.

## Context

- **What exists.** The required `tofu-checks` job formats, validates and tests the
  configuration with the providers mocked. It needs no state or credential, so it
  cannot see a plan
  ([`pipeline.md`](../../topics/engineering/ci/pipeline.md)). The promotion checklist
  lists `tofu -chdir=tofu plan`, then an apply once the plan is read. It is advice, no
  ruleset requires it, and it runs on `pull_request_target` with a write token precisely
  because it checks nothing out of the pull request
  ([`pipeline.md`](../../topics/engineering/ci/pipeline.md#promotion-checklist)).
- **Where Tofu runs.** On the operator host, with its credentials in a file outside the
  repository ([ADR 0058 (Operator work host)](../0058-where-operator-work-runs/revision-000.md),
  [ADR 0048 (Tofu credentials)](../0048-where-tofu-credentials-live/revision-000.md)).
  The CD agent takes no part in Tofu. State is a local file until a remote backend is
  decided in [`tofu-migration.md`](../../projects/tofu-migration.md).
- **A plan runs the branch's code.** `tofu plan` evaluates the configuration, and its
  providers and modules, with the infrastructure credential in the environment. A data
  source, a module source or a provider override in a pull request can act with that
  credential. A plan of a pull request branch therefore runs only where the maintainer
  has already read the diff, as [ADR 0050 (Agent changes to production)](../0050-agent-authored-changes-reaching-production/revision-000.md)
  requires for any change before it is checked out where it executes.
- **A plan needs state.** A plan in CI would have nothing to compare to, and a copy of
  the state published to CI is a second credential-adjacent artifact to keep fresh that
  still would not be the real plan.
- **Some failures appear only in a plan against real state.** A `moved` block whose
  target address a new module also declares fails at plan time against the real state,
  and no check without state sees it.
- **What a state-less check can see.** `tofu graph -type=plan` after
  `tofu init -backend=false` needs no credential or state. Run on OpenTofu 1.13.2 against
  a configuration with no state, it lists one node per resource or module call:
  - a `for_each` resource is one node, so the removal of one instance is invisible;
  - a resource renamed by a `moved` block shows only its new address, so the old address
    reads as removed unless the `moved` blocks are read too;
  - a replacement caused by an attribute change is not visible at all.
- **What a plan file shows.** `tofu show -json` of a saved plan lists
  `resource_changes[]`, each with `address`, `change.actions`, `previous_address` for a
  move and an `action_reason`. A replacement is `["delete","create"]`, or
  `["create","delete"]` under `create_before_destroy`. `resource_drift` is absent when
  nothing drifted.
- **The repository is public.** No credential in CI, and no value from a plan in a
  comment. A summary carries resource addresses and action names, which the repository
  already shows.

## Decision

Review splits along what each place can know. The guard is the part that enforces; the
rest makes the destroys visible earlier.

1. **A guard over a saved plan.** A pure function reads `tofu show -json` of a saved plan
   and `tofu/plan-intent.yaml`, and returns `ok`, `needs-declaration` or `violation` with
   a summary of addresses and actions. It reads no state and uses no network.
2. **The apply wrapper applies the checked plan.** It plans to a file, runs the guard,
   prints the summary, copies the state, and applies that plan file only on `ok`. If
   state changed between plan and apply, Tofu refuses the file, so nothing unchecked is
   applied.
3. **A plan before merge, on the operator host.** After reading the diff, the maintainer
   plans the branch in a clean worktree, read-only, and pastes the summary into the pull
   request. This is the simplified plan on the pull request, and it is what catches a
   failure that only real state shows.
4. **A credential-free check on the pull request.** A required job compares the
   resource and module addresses at the base and at the head, reading `moved` blocks, and
   fails when an address of a protected type disappears without an allow-list entry in
   the same pull request.
5. **The CD agent is not given Tofu here.** A plan-only job there needs a read-only
   credential and state it can reach, and that is its own decision, as ADR 0058 and
   [ADR 0044 (CD agent trigger)](../0044-prod-automation-trigger-and-execution/revision-000-c.md)
   place Tofu on the operator host. The guard is the same command wherever it later runs.

**Rules.** Evaluated over `resource_changes[]`:

| Rule | Behaviour |
| :--- | :--- |
| G1 | A create, an in-place update, a no-op, a read and a move pass without a declaration |
| G2 | A delete or a replace of a protected type needs an allow-list entry for the same address with a covering action; otherwise `needs-declaration` and a non-zero exit |
| G3 | A type is protected unless the guard's configuration lists it as safe to destroy; the list starts empty |
| G4 | An allow-list entry that no change in the plan matches is reported as stale; it is an error once the apply it was for is done |
| G5 | Any `resource_drift` is listed and never silently accepted |
| G6 | More than a set number of resource changes in one plan needs a one-line acknowledgement |

**The allow-list** is `tofu/plan-intent.yaml`. Each entry names one address, the actions
it permits and a neutral reason, and may carry an `until` date no more than fourteen days
ahead.

```yaml
allow:
  - address: module.example.proxmox_virtual_environment_vm.this
    actions: [delete]
    reason: The earlier machine is retired after its dump
```

An entry is a permission, not a prediction. A merge can come days before its apply and
several pull requests can land before one apply, so entries stay until the apply they
cover is done and a follow-up removes them. The entry is in the same pull request as the
change that needs it, so the reviewer reads "this change can destroy X" as one added line.

**Not decided here:** which resource types are protected beyond the default of all of
them, the size that triggers G6, and where the plan before merge runs on the operator
host. Each is a value or a detail of the build, held by the project that builds it.

## Alternatives considered

- **A guard at apply time only.** Necessary and not enough: the surprise arrives after
  the merge, and the pull request still shows only edited lines.
- **`tofu plan` in GitHub Actions with a Proxmox token.** It puts a secret in a public
  repository's CI, runs a branch's code with it, and still has no state.
- **A plan against a sanitised copy of the state in CI.** The provider still configures
  against the API, the copy is another artifact to keep current, and the result is not the
  real plan.
- **The CD agent applies after merge.** Needs a write-scoped infrastructure credential on
  an always-on host, which ADR 0048 chose against, and a remote backend. Revisit once the
  backend is decided.
- **Reusing the promotion checklist workflow to post plans.** It has a write token because
  it never touches pull request code, and a plan needs that code. It is advice, so it
  cannot enforce.

## Assumptions

- **Claim:** The plan of the real configuration, with the Proxmox provider and the real
  state, reports every destroy and replace as an entry in `resource_changes` with
  `delete` in its actions. The field names and the action orders above were read from a
  plan of the built-in `terraform_data` resource on OpenTofu 1.13.2.
  **Breaks if wrong:** The guard would pass a destroy it cannot see.
  **Checked by:** `tofu show -json` of a saved plan of `tofu/` on the operator host.

- **Claim:** Tofu keeps running on the operator host that ADR 0058 describes, and not on
  another machine.
  **Breaks if wrong:** Where the wrapper and the plan before merge run, and which
  credential file they read.
  **Checked by:** ADR 0058 reaching `approved`, or a revision of it that moves Tofu.

## Consequences

- A change that destroys or replaces a protected resource carries one more line, the
  allow-list entry, and every apply goes through the wrapper instead of a bare
  `tofu apply`.
- The pull request check sees additions and removals of addresses only. A replacement
  caused by an attribute, a removed `for_each` instance and a state-dependent failure are
  left to the guard and to the plan before merge, so the check is not relied on alone.
- An agent-authored pull request can add an allow-list entry like any other edit. The
  protection is the same as for any file: the maintainer reads the diff and the ruleset
  requires the checks. A second reviewer would make `CODEOWNERS` on this one file the
  cheap tightening.
- The agent has no view of Tofu changes until Tofu moves to a host it can reach; the
  promotion checklist keeps listing them as run by hand.
- The behaviour, once built, is described in a topic doc under `docs/topics/infra/`.

## Invariants

- An apply runs only a plan file the guard returned `ok` for.
- A delete or replace of a protected type is applied only with a matching allow-list
  entry.
- No credential for the infrastructure is available to a job that runs on a pull
  request, and no plan value other than addresses and action names is printed to one.
- A plan of a branch's code runs only after the maintainer has read the diff.

## Non-goals

- Judging an in-place update by its attributes. A disk or network change can destroy in
  effect; a type can be flagged for review under G1 if a real case shows it matters.
- Applying from the CD agent, or a remote state backend.
- A plan in CI.
- Reviewing the Ansible or Compose side of a change.

## Validation

Unit tests of the guard with canned plan JSON, a control for each rule that fails without
it, and a test of the wrapper with a stubbed `tofu` that shows the saved plan is the one
applied. The pull request check is a required job.

## Reconsideration triggers

A second maintainer; external pull requests; Tofu credentials moving off the operator
host; a remote backend landing; or a provider gaining a plan mode a mock can drive, which
would make a plan in CI meaningful.
