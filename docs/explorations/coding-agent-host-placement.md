---
id: EXP-coding-agent-host-placement
title: "Where should the coding-agent host run: on the node, or on a cloud instance?"
type: exploration
status: open
summary: "Whether the coding-agent host stays a VM in its own VLAN on the one Proxmox node or runs on demand on a cloud instance, and what that changes for its egress, management and access."
topic: security-hardening
related: [ADR-0045, ADR-0051, ADR-0053, ADR-0054, ADR-0055, ADR-0116]
---

# Where should the coding-agent host run: on the node, or on a cloud instance?

The coding-agent host is planned as a VM in VLAN 30 on the Proxmox node
([ADR 0051](../decisions/0051-coding-agent-execution-isolation/revision-000.md),
[ADR 0053](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md)).
It is the largest single host the node would take on
([`node-capacity.md`](node-capacity.md)), and a cloud instance could host it
instead. Its isolation, egress, management and access each rest on where it
runs, so the placement is decided before the stages that build it.

## What bears on it

- **What is built.** Only the first stage of the zone project is under way, which
  carries VLAN 30 in the gateway's play. Applying the zone to the production
  gateway, the host, its role, its egress path, its lifecycle and its access path
  have not started.
- **It already runs on demand.** [ADR 0054](../decisions/0054-managing-an-untrusted-host-from-the-cd-agent/revision-000.md)
  starts it when the maintainer wants the agent and rebuilds it from its Tofu
  definition each time, so it need not exist between sessions. That fits an
  instance created for a session, and it does not need an always-on cloud host.
- **Isolation.** ADR 0051 rests on a dedicated VM, without nested virtualization,
  on a hypervisor shared with the rest of the lab. A cloud instance shares none of
  that hypervisor and sits in another provider's account.
- **Egress.** The coding-agent zone reaches the Internet only through the
  untrusted-tier proxy of [ADR 0116](../decisions/0116-internet-egress-for-hosts-in-default-deny-zones/revision-000.md),
  which filters by destination name. A cloud network filters by address, so a
  host there still needs a filtering proxy beside it. The untrusted-tier proxy
  also serves the DMZ, so it cannot leave with the coding-agent host unless the
  DMZ's consumer leaves too. A proxy idled at about 45 MB resident on a 2 GB VM
  in an earlier measurement, so one beside the host would need little.
- **Management.** The CD agent converges the host over SSH from a job that holds
  only the host's key. Building the host on a cloud provider adds a provider
  credential to whatever creates it, which is the subject of
  [`cloud-credential-custody.md`](cloud-credential-custody.md).
- **Access.** The maintainer's laptop reaches the host over a route that only
  the laptop is granted. A cloud instance joins the tailnet as a node with a
  tag, and the grant is written against the tag.
- **The cloud allowance.** Oracle's documented Always Free Ampere allowance is
  pooled hours per month, not a cap on what runs at once: 3,000 OCPU-hours and
  18,000 GB-hours a month is 4 OCPU and 24 GB running all month, and 1,500 and
  9,000 is 2 OCPU and 12 GB. It was cut from the first to the second on 15 June
  2026. The account here is pay-as-you-go, and Oracle support is reported to
  have said that such accounts keep the larger allowance. That is not published
  policy, and it is to be checked against Oracle's own pages and the account's
  usage page before anything relies on it. Beyond the allowance a run is billed
  by the hour at a rate on Oracle's price list, which is to be read there.
- **Who else wants it.** The security-event pipeline of
  [ADR 0045](../decisions/0045-security-event-collection-and-alerting/revision-000.md)
  plans the same allowance for Wazuh, at a size now being considered of 2 OCPU
  and 8 GB. Wazuh's documented minimum for a single-node stack is 4 cores and
  8 GB, so 2 OCPU is half the cores. ADR 0045 holds whether it is adequate as an
  open assumption with a spike, and for the monitored set this question adds
  nothing to it. Its images on Arm64 are a second check that record names.
- **The sums.** Wazuh at 2 OCPU and 8 GB all month, and the host at 2 OCPU and
  8 GB while it is up, is 4 OCPU and 16 GB at once. Against the larger allowance
  that fits in a pool of 3,000 OCPU-hours even if the host ran all month (about
  1,460 hours for Wazuh, leaving about 1,540, or 770 hours of the host). Against
  the smaller allowance it is over by 2 OCPU and 4 GB while the host is up, and
  the OCPU pool is the one that runs out, with about 40 hours left after Wazuh
  and so about 20 hours of the host before billing.
- **Architecture.** Ampere is Arm64. The role, the sandbox and Claude Code on
  Arm64 are not tested here. The other free instances are too small: Oracle's
  AMD micro instances are 1 GB, and Google's free instance is 1 GB with 1 GB of
  free outbound transfer a month.
- **Capacity to create.** An instance created for each session needs the region
  to have Ampere capacity at that time. Whether it often does not is to be
  checked, and a host that is stopped and restarted may have the same problem.
- **Not examined here.** Moving other hosts off the node, such as the apps of
  `services` that could sit in a DMZ. That is a separate question with its own
  options.

## Options

- **Stay on the node.** What the projects plan. It keeps one provider, one
  firewall and one set of flows, and it takes 8 GiB of a node that the planned set
  already exceeds, and it leaves the host sharing a hypervisor with the lab.
- **A cloud instance created for each session.** The instance is built from its
  Tofu definition at each start and destroyed after, with a filtering proxy
  beside it. It takes nothing from the node and sits behind another provider's
  boundary. It costs a provider credential in the creating job, a second place
  that holds the egress rules, and a dependency on capacity at the moment of
  creation.
- **A cloud instance that is stopped between sessions.** Keeps the disk and
  avoids rebuilding, which ADR 0054 chose against, and costs the boot volume's
  share of the allowance.
- **A small paid instance outside any free allowance.** Avoids the allowance and
  the Wazuh competition for it, at a monthly cost and the same Arm64 and
  credential questions if it is Arm.

## Leaning

An instance created for each session, if Arm64 and capacity are shown to work, since
the host already runs on demand and the node has no room for it. The stages that
build the host, its egress, its lifecycle and its access path wait on this, and
the zone project's first stage can finish. What would change it: Claude Code's
sandbox not working on Arm64, Ampere capacity often missing at session start,
or the provider credential in the creating job turning out harder to hold than
the node's room is worth.
