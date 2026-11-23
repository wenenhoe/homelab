---
id: EXP-production-rebuild-rehearsal
title: "What would rehearse a production rebuild of the gateway before the window?"
type: exploration
status: open
summary: "The scratch gateway rehearses the module and the play, and the preflight reads the root module and the live token's rights, but nothing yet runs the order of the window; what would, and at what cost."
topic: deployment-platform
related: [ADR-0089, ADR-0094]
---

# What would rehearse a production rebuild of the gateway before the window?

A rebuild of the production gateway is a sequence: dump, destroy, create, first boot, update, snapshot, apply, check. The scratch runs prove the module and the play on an isolated bridge. A read-only preflight ([`gateway_preflight.sh`](../topics/disaster-recovery/rebuild-tools.md#gateway_preflightsh)) reads what the window needs before anything is stopped and before the create: the root module's plan, the image, the dump, the snapshot route and the grant. It does not run the sequence. Which of the sequence's other parts a rehearsal should cover, and how, is not decided.

## What bears on it

- A scratch run builds the gateway from the module under `tofu/scratch/opnsense`, with its own VMID, bridges and no startup order. It does not apply the root module, so what the root declares (the VMID, the bridges, the startup order, the image volume and the seed variable) is not exercised by it.
- The Tofu user's role on the node was written for the Ubuntu hosts and the scratch gateway. A VM's startup order needs a privilege on `/` that the role does not hold, which a scratch run does not reach because it sets no order.
- The image is older than the release the play pins. The scratch gateway's script updates it as part of a run, and a rebuild list written separately from that script has to repeat the step.
- A scratch spec passes the play's variables as typed values. The same variables on the command line are strings unless given as JSON, which the play refuses for a boolean.
- A `--check` on a gateway the play has never applied cannot finish, since nothing it reads exists yet; a spec applies first and checks after.
- The runner's step kinds are the play, the flows, a block rule, the VLANs, a canary VM and a stray rule. None of them dumps, destroys or creates the gateway.
- The flow probes need a canary VM in each zone they test, and production builds one only when a key is set.

Still to check: whether the root module can take a scratch VMID without a copy of it, and what a scratch plan of the root would show of the production hosts.

## Options

- **A rebuild spec for `scratch_run`.** New step kinds (dump, destroy, create, update, snapshot) let a scratch gateway stand in for the production one and run the whole sequence and its checks. It proves the order and the script together. It stands in for the production values and does not exercise the root module or the live token.
- **A scratch apply of the root module.** The root takes the gateway's VMID and bridges as variables for a rehearsal, with state of its own. It would exercise the root's declaration and the role. It risks a plan that names the production hosts, and the state has to be kept apart from the real one.
- **A runbook generated from the steps.** The window's commands come from the same list the rehearsal runs, so a step cannot be in one and not the other. It does not prove anything by itself.

## Leaning

A rebuild spec, if rebuilds recur, with the runbook generated from its steps; the preflight already covers the checks a rehearsal on the isolated bridge cannot. A scratch apply of the root is weighed again if the root grows further declarations of its own.
