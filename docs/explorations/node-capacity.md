---
id: EXP-node-capacity
title: "Does the node have room for the hosts planned for it, and how is its headroom judged?"
type: exploration
status: open
summary: "Whether the always-on hosts, the Windows machines and the scratch runs fit on the one Proxmox node, and whether headroom is budgeted by configured memory, by measured use or by named run sets."
topic: deployment-platform
related: [ADR-0035, ADR-0053, ADR-0058, ADR-0092, ADR-0114, ADR-0116]
---

# Does the node have room for the hosts planned for it, and how is its headroom judged?

Several decisions add a VM to one Proxmox node and call its headroom limited: [ADR 0116](../decisions/0116-internet-egress-for-hosts-in-default-deny-zones/revision-000.md) adds two proxies, [ADR 0114](../decisions/0114-landing-a-series-from-a-device-other-than-the-laptop/revision-000.md) the Gatehouse host, [ADR 0058](../decisions/0058-where-operator-work-runs/revision-000.md) the operator host, and the coding-agent host and the CD agent are planned too. The only accounting of the node is the early one in [ADR 0035](../decisions/0035-container-orchestration-platform/revision-000.md), taken before most of these existed. Each record sizes its own VM, and none asks whether the set fits.

## What bears on it

- **The node.** One Proxmox node with a 6-core i5-9400 (six physical cores, no hyperthreading), 32 GB of RAM (31 GiB reported) and 8 GiB of swap, with kernel same-page merging active. The repository declares no second node.
- **What is allocated now.** The guests that run today are allocated 24 GiB of the 31 GiB:

  | VM | Name | RAM (GiB) |
  | :-: | :--- | :-: |
  | 201 | OPNsense | 2 |
  | 202 | tailscale | 2 |
  | 203 | services | 2 |
  | 204 | play | 4 |
  | 205 | security | 2 |
  | 206 | storage | 4 |
  | 401 | Development | 8 |

  With them running, the node reported about 11 GiB available. The stopped guests are 103, 104, 105, 402 and 403, each allocated 4 to 8 GiB, and the cloud-init template 106.
- **What changes in the plan.** VM 201 is rebuilt from the seed, and its size is set again then. VM 401 is replaced by the operator host and the CD agent. VM 402 is removed. VMs 403 and 103 to 105 may be managed by [`windows-vms.md`](../projects/windows-vms.md) later.
- **What is new.** The two proxies, the Gatehouse host, the operator host, the coding-agent host and the CD agent, plus the scratch gateways and test VMs a run creates, several at a time on the same node. Only the CD agent has a size in its record, 2 to 4 GB. An earlier measurement had Squid holding about 45 MB resident on a 2 GB VM ([ADR 0053 revision 0](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md)), so a proxy's memory is mostly the VM's floor, not the proxy.
- **The Windows machines decide most of it.** Allocated together, 103, 104, 105 and 403 come to 28 GiB, almost the whole node. The one with a GPU is attached by a PCI mapping, which pins its memory while it runs, so ballooning and same-page merging do not reclaim it. Whether they run on demand, one at a time or together is not recorded.
- **CPU has the same shape and no measurement.** ADR 0035 counted 12 vCPU on five VMs over six cores already, and the VMs planned since add to that. Contention has not been measured.
- **Not examined here.** The disks: the NVMe holding the VM disks, the node's root file system and the backup drive.

## Options

- **Budget by named run sets.** One table of what runs always, what runs on demand (the Windows machines) and what runs only during a scratch run, each with a memory ceiling, kept beside the VMID scheme in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md). It answers the Windows question directly and costs a table to keep true.
- **Check configured memory in code.** A check sums the always-on VMs' memory from the Tofu inputs against a stated ceiling. It stops a VM that does not fit at review time, and it measures allocation, not use.
- **Budget by measured use.** Size each VM from what monitoring shows it using. It matches what the node really spends, and needs a window of history for hosts that do not exist yet.
- **Size each VM as it arrives.** What happens today. It has no point at which the set is added up.
- **A second node.** Adds hardware, a cluster or a second state, and the repository declares one node. It is the answer only if the set does not fit under any of the above.

## Leaning

None yet. Three facts decide it: the sizes of the operator host, the Gatehouse host and the coding-agent host, which no record gives; how the Windows machines are run; and how much memory the node itself and a scratch run need kept free.
