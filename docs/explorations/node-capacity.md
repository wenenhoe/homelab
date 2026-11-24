---
id: EXP-node-capacity
title: "Does the node have room for the hosts planned for it, and how is its headroom judged?"
type: exploration
status: open
summary: "Whether the always-on hosts, the on-demand Windows machine and the scratch runs fit on the one Proxmox node, and whether headroom is budgeted by configured memory, by measured use or by named run sets."
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
- **What is new.** The two proxies, the Gatehouse host, the operator host, the coding-agent host and the CD agent, plus the scratch gateways and test VMs a run creates. Only the CD agent has a size in its record, 2 to 4 GB. The sizes now being considered are 4 GiB for the operator host, 2 to 4 GiB for the Gatehouse host, 8 GiB for the coding-agent host and about 2 GiB for each proxy. An earlier measurement had Squid holding about 45 MB resident on a 2 GB VM ([ADR 0053 revision 0](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md)), so a proxy's memory is mostly the VM's floor, not the proxy.
- **The Windows machines.** VMs 103, 104 and 105 are templates and never run. VM 403 is allocated 8 GiB and runs on demand, as a gaming machine that plays on the `play` host's Minecraft server. Its GPU is attached by a PCI mapping, which pins its memory while it runs, so ballooning and same-page merging do not reclaim it.
- **The `security` host may shrink.** Monitoring is planned to move to an off-site host ([`off-site-monitoring.md`](../projects/off-site-monitoring.md)). VM 205 is allocated 2 GiB today, and its size would be set again once monitoring is out of it; how much it needs then is not known.
- **The reserve.** 2 to 4 GiB is kept free for the node itself.
- **A scratch run may need machines powered down.** A scratch gateway and its canary VMs are created on the same node as the always-on set, and whether they fit beside it, or only with some hosts stopped for the run, is not settled. A run that needs hosts stopped is a run set that excludes them, not headroom.
- **What the planned set adds up to, by allocation.** The always-on hosts that stay are the six rows above other than VM 401, 16 GiB. VM 401 leaves, and the planned hosts add 4 for the operator host, 2 to 4 for the CD agent, 2 to 4 for the Gatehouse host, 8 for the coding-agent host and 4 for the two proxies: 36 to 40 GiB in all, less whatever `security` gives back. The node offers 31 GiB less the 2 to 4 GiB reserve, 27 to 29, so the set is over by 7 to 13 GiB before VM 403 or a scratch run, and by 15 to 21 with VM 403's 8 GiB. Without the coding-agent host it is 28 to 32 before VM 403, which is at or over the same line. It counts allocation, not use: a VM's configured memory is not what it holds, and the early accounting in ADR 0035 already relied on that.
- **CPU has the same shape and no measurement.** ADR 0035 counted 12 vCPU on five VMs over six cores already, and the VMs planned since add to that. Contention has not been measured.
- **Not examined here.** The disks: the NVMe holding the VM disks, the node's root file system and the backup drive.

## Options

- **Budget by named run sets.** One table of what runs always, what runs on demand (the Windows machines) and what runs only during a scratch run, each with a memory ceiling, kept beside the VMID scheme in [`vm-provisioning.md`](../topics/infra/vm-provisioning.md). It answers the Windows question directly and costs a table to keep true.
- **Check configured memory in code.** A check sums the always-on VMs' memory from the Tofu inputs against a stated ceiling. It stops a VM that does not fit at review time, and it measures allocation, not use.
- **Budget by measured use.** Size each VM from what monitoring shows it using. It matches what the node really spends, and needs a window of history for hosts that do not exist yet.
- **Size each VM as it arrives.** What happens today. It has no point at which the set is added up.
- **Run the coding-agent host off the node.** It is the largest single item. The host would run on a cloud instance instead, which the set then needs no room for. It changes what the host's isolation rests on: the coding-agent zone is a VLAN of this node with a default-deny gateway, and a cloud instance has neither, so [ADR 0053](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md)'s reach rules, the egress proxies and the access path would each need restating for it. It is not recorded elsewhere yet.
- **A second node.** Adds hardware, a cluster or a second state, and the repository declares one node. It is the answer only if the set does not fit under any of the above.

## Leaning

Budget by named run sets, with the always-on memory checked against a ceiling in code. The Windows question is answered: the templates are outside the budget and VM 403 is one on-demand set of 8 GiB. The sums above show the always-on set does not fit with the coding-agent host on the node, so the open choice is that host's placement more than how headroom is judged. Two facts still decide the sets: how far `security` shrinks once monitoring leaves it, and which hosts a scratch run needs stopped.
