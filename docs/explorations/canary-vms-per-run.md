---
id: EXP-canary-vms-per-run
title: "Should a zone's canary exist only for the length of a run?"
type: exploration
status: open
summary: "The flow list's canaries are declared as resident VMs; the scratch runs build one for a run and remove it. Which suits production, given a node with little spare memory."
topic: deployment-platform
related: [ADR-0094]
---

# Should a zone's canary exist only for the length of a run?

[ADR 0094](../decisions/0094-showing-the-network-boundary-behaves-as-declared/revision-000.md) has the probes run from a small VM in each zone, after each apply to the gateway and on a schedule against production. The root module declares the services canary (VMID 208) as an ordinary VM when a key is set, so it stays up between runs. The scratch runs already build a canary for the length of a run and remove it. The node has little memory to spare, so a canary in each of six zones, always on, is a cost to weigh against building one when a run needs it.

## What bears on it

- A canary is `proxmox_ubuntu_vm` at the zone's `.8` address: 1 core, 1 GB of memory, 8 GB of disk, with its VLAN and address from its VMID.
- Only the services canary is declared. The other zones' canaries wait for the gateway to admit the runner's SSH to them, so the resident cost today is one VM and grows to six.
- A scratch run builds its canary from `tofu/scratch/ubuntu` with `-backend=false` and a state file outside the checkout, and `tofu destroy` with that state removes it at teardown. The canary's VMID is the one the VMID scheme gives its zone, so the VM takes the canary's address. Nothing about it is written to the root's state.
- A production run from the same configuration would put the VM on the VLAN-aware bridge with the zone's tag. The Tofu user's role already covers that bridge and the VMs.
- The root module and a per-run build cannot both own VMID 208, so the root declares a zone's canary only if the build is not used for that zone.
- The runner reaches a canary over SSH from the operator host, and the canary holds no credential, so a per-run VM carries the same public key and nothing else.
- The scratch runs also have a namespace stand-in on the node, joined to the gateway's bridge with the zone's VLAN tag, which costs no VM.

A canary built this way on the production gateway's VLAN 20 took 29.5 seconds to apply and answered over SSH about a second after, so a run waits half a minute for it. Each build gets a fresh host key, so the runner's `known_hosts` entry for the canary's address has to be cleared before the run or its host key accepted as new, and the flows were probed with that entry fresh.

Still to check: what a run that dies before its destroy leaves behind, and how it is found.

## Options

- **Resident canaries (today).** Runs start at once and nothing has to be built. Every zone adds a VM that is up all the time, and a host in an untrusted zone with an inbound SSH flow.
- **Declared but stopped, started for a run.** Nothing runs between runs, and the VM is Tofu's. The runner needs a way to start and stop it, a wait for the boot, and Tofu's handling of a stopped VM has to be checked.
- **Built for the run and destroyed after it, with a state of its own.** The same configuration the scratch runs use, with the production bridge, the zone's VMID and a state file kept for the run only. No standing VM and no change to the root's state. A run waits for the build, and a run that dies leaves a VM that is found by its name and VMID, or by the state file if it was kept. The root declares no canary for that zone.
- **A namespace on the node.** The scratch stand-in, joined to the production bridge with the zone's tag. No VM and no build time. The canary then runs as root on the node, which is also a host the flows test ([`network-boundary-checks.md`](../topics/infra/network-boundary-checks.md)), and the ADR's "outside every host under test" does not hold for it.

## Leaning

Built for the run, with a state of its own, because it keeps the node's memory free and reuses what the scratch runs prove. It needs a clean-up for a run that dies and a known_hosts step for each build. A scheduled production run then holds the Proxmox credentials and Tofu on the host that runs it, which the operator host already does. The namespace is worth a second look only if a half-minute build proves to be the problem.
