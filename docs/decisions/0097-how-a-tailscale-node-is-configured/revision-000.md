---
id: ADR-0097
revision: 0
type: adr
title: How a Tailscale node is configured
short: Tailscale node configuration
solution: A small repo-owned role converges the node against its own preferences and joins it, tagged, with a one-time key supplied at run time
summary: How a host's Tailscale client is installed, joined to the tailnet and kept configured, given that the join key is a credential and the policy keys off the node's tag.
topic: deployment-platform
status: working
related: [ADR-0015, ADR-0040, ADR-0043, ADR-0049, ADR-0053, ADR-0058, ADR-0059, ADR-0089]
---

# 0097. How a Tailscale node is configured

## Problem

The tailnet is the maintainer's path into the lab away from home, and the subnet router is the one node that carries it. That node's installation, join and preferences have to be rebuildable from the repository, and the credential that joins it has to be handled without a standing secret. The tailnet's own policy is a separate problem ([ADR 0059 (Tailnet policy)](../0059-where-the-tailnet-policy-is-defined/revision-000.md)); this one is the node.

## Context

- **The router is hand-built today.** VM 202 advertises `192.168.20.0/24`, carries no tag, has source NAT on, the tailnet's DNS accepted and the client's own auto-update on, and has Tailscale SSH off. Its forwarding sysctls are persisted in `/etc/sysctl.d/99-tailscale.conf`, and its unit and `/etc/default/tailscaled` are the package's. Its status reports no key expiry. It was installed with the vendor's install script, which left a one-line `tailscale.list` source and a keyring package. The host's unattended upgrades take security origins only and its local override only removes unused packages, so Tailscale's repository is outside them.
- **Nothing in the repository configures it.** The host is patched through `maintenance.yaml` as a `network_infra` member and nothing else.
- **The policy keys off the tag.** `tagOwners` names who may apply a tag, route auto-approval is keyed on the node's tag, and a node joined with a tagged key is not owned by a user. Tailscale turns key expiry off for a tagged device by default, and a subnet router whose key expires stops forwarding ([Key expiry](https://tailscale.com/docs/features/access-control/key-expiry)). A rebuilt node that joins untagged would take the domain's default expiry.
- **A rebuild is a new device.** The node's identity is its state file, which holds its private key. A rebuilt VM that joins again has a new device entry and a new tailnet address.
- **Subnet routers source-NAT by default**, so the gateway sees every tailnet caller as the router ([ADR 0089 (OPNsense configuration)](../0089-how-the-opnsense-gateway-is-configured/revision-000.md)).
- **`artis3n.tailscale` v1.2.1** is the maintained collection for the node side, MIT-licensed, with one role. Its role stops unless `tailscale_authkey` is set on every run that does not skip `tailscale up`. It runs `tailscale up` again when a hash of the arguments and key changes, a hash it keeps in the login user's home directory, and it does not compare the node's actual preferences. `tailscale up` is a plain command task. It installs the package and the apt repository for several distribution families and sets no forwarding sysctl.
- **`tailscale set` converges the preferences on a logged-in node without a key.** On an Ubuntu 26.04 node running Tailscale 1.104.4, joined untagged with a one-time key, a single `tailscale set` call changed the advertised routes, turned the accepted DNS setting off and turned the client's auto-update off, with no key. The node's own report (`tailscale debug prefs`) then showed `AdvertiseRoutes`, `CorpDNS: false` and `AutoUpdate.Apply: false`, and showed the same values after a restart of `tailscaled` and after a reboot of the VM, with the node still logged in. `set` takes one flag per preference and changes only the ones named. `AutoUpdate.Check` stayed `true`: it is the notice of available updates, a separate flag (`--update-check`) that the role leaves alone. The node had no Tailscale timer or apt configuration file after the change, so the client's updater is the in-process one that `AutoUpdate.Apply` controls. The values before the call were not recorded, so which of them `set` changed is not shown.
- **Join keys are credentials** that [ADR 0015 (Cloud credential expiry)](../0015-cloud-credential-expiry/revision-000.md) expects to expire. An OAuth client that mints them does not expire on its own and can add any node under the tags it may apply.
- **The router is not always on yet, and will be.** Spike VMs are created and removed on the Proxmox node while VM 401 is in service, and the router VM or its host has been shut down for days at a time. [ADR 0058 (Operator work host)](../0058-where-operator-work-runs/revision-000.md) makes a Tailscale route to VLAN 30 the laptop's only way to the operator host, so once the operator host and the laptop replace VM 401 every operator session crosses the router and it has to run all the time.
- **The Proxmox node is already a member.** It joined by hand as an ordinary node with no approved route, and it is the maintainer's way to the hypervisor when the router VM is broken, so it is the one way in that does not cross the router. It is outside the `network_infra` group.
- **Other hosts may join.** [ADR 0049 (Site-loss monitoring)](../0049-monitoring-that-survives-loss-of-the-site/revision-000.md) extends the router's reach to a GCP node, which may have to join the tailnet itself. The coding-agent host and the operator host do not join.

## Decision

**A repo-owned role**, `tailscale_node`, applied to the `network_infra` group. No collection is a dependency.

The role converges, in order:

1. **Install** from Tailscale's apt repository in the same DEB822 form the `docker` role uses for Docker's, and start `tailscaled`. Where the node has the vendor script's one-line source, the role removes that file in the same run, so apt does not see the repository twice.
2. **Forwarding.** When the node advertises routes, a sysctl drop-in sets IPv4 and IPv6 forwarding.
3. **Join**, only when the node is logged out. The role then requires a one-time key and passes it with the node's tag. A node that is already logged in needs no key, and a missing key on a logged-out node stops the play before anything changes.
4. **Preferences**, compared against what the node reports and applied with `tailscale set` for each one that differs. The role names every preference it owns: the advertised routes, the accepted DNS setting, and the client's auto-update, which is off. Source NAT stays at its default.

**The tag and the routes.** The node joins with one tag, `tagOwners` names the maintainer as its owner, and `autoApprovers` approves the routes it advertises. Both live in the tailnet policy, which [`tailnet-policy-baseline.md`](../../projects/tailnet-policy-baseline.md) writes by hand and [ADR 0059](../0059-where-the-tailnet-policy-is-defined/revision-000.md) later carries into OpenTofu unchanged. The routes the node advertises are a host variable, so a new zone's route is a change to that variable and one grant in the policy.

**The join key** is made in the Tailscale admin console for the rebuild: single-use, pre-authorized, tagged, and valid for hours. It reaches the play as a run-time variable from the operator's environment, is not logged, and is not written anywhere.

**Updates.** Only apt updates Tailscale, through `maintenance.yaml`, one host at a time like every other package. The client's own updater is off, and the host's unattended upgrades take security origins only ([ADR 0043 (Host hardening baseline)](../0043-host-os-hardening-baseline/revision-000.md)), so a Tailscale release reaches the router when that play runs against `network_infra` and not before.

**What Molecule covers.** The install, the forwarding drop-in, the preference comparison against a stub client whose output is copied from a real node, and the refusal to join without a key. The join itself needs a control plane, so it is checked on a real node, and a `--check` run after it reports no change.

## Alternatives considered

- **The `artis3n.tailscale` role as it is.** It needs a key on every run, so a routine run of the group would have to hold one, and its change detection reads its own hash rather than the node, so a route changed by hand goes unseen.
- **That role for the install, with `tailscale_up_skip` and the join written here.** It would replace a few tasks that already have a model in the `docker` role, with a pinned dependency and support for distributions the lab does not run.
- **Other published roles and collections.** They are younger and no better documented, and none was found that converges against the node's actual preferences, joins without a key once logged in, and sets forwarding.
- **An OAuth client that mints the key at run time.** It is a standing credential that can add tagged nodes to the tailnet and does not expire on its own.
- **A key from the `tailscale_key` resource in OpenTofu.** It puts the key in Tofu's state, which [ADR 0059](../0059-where-the-tailnet-policy-is-defined/revision-000.md) rules out.
- **The router as a container on `services` or another host, with no VM of its own.** The gateway tells tailnet callers apart only by the router's address, so a container that shares its host's address makes every rule that admits the router, such as [ADR 0053 (Coding-agent network reach)](../0053-network-reach-of-the-coding-agent-host/revision-000.md)'s admission to its VLAN, admit that host, and a separate address needs macvlan on the host's NIC. The route would also depend on a host that is deployed to and rebuilt, so every such change would cut the maintainer's way in. Routing in the kernel needs `NET_ADMIN` and `/dev/net/tun`, against the `cap_drop: [ALL]` default. [ADR 0040 (Tofu VM DNS)](../0040-dns-for-tofu-provisioned-vms/revision-000.md) already keeps the router from a second job because it is the remote-access path.
- **Carrying `tailscaled`'s state file across a rebuild.** It keeps the node's identity but puts its private key into a backup, and the repository's backups cover application data, not host state.

## Consequences

- A rebuilt router is a new device. The old device is removed in the console, and the policy's grants for the router name its tag, never its address.
- While the router is rebuilt the tailnet has no route into the lab. The dump of the old VM is the way back ([`tofu-migration.md`](../../projects/tofu-migration.md)), and the Proxmox node's own membership reaches the hypervisor meanwhile. That membership helps when the router VM is broken, not when the node itself is off.
- The router's size is judged under the operator traffic, not at idle ([`tofu-migration.md`](../../projects/tofu-migration.md)).
- [ADR 0043 (Host hardening baseline)](../0043-host-os-hardening-baseline/revision-000.md) lists `net.ipv4.ip_forward: 0` among the `sysctl` area's defaults. When that area is added, it must leave forwarding on for a node that advertises routes, and the role owns that value.
- A Tailscale release reaches the router only as often as `maintenance.yaml` runs against it, and an upgrade can restart `tailscaled` and drop the flows it forwards. Adding Tailscale's repository to the unattended origins would loosen ADR 0043's security-only rule, so it is not done here.
- A host firewall added by the hardening baseline ([ADR 0043](../0043-host-os-hardening-baseline/revision-000.md) names `ufw`, which the repository does not configure today) has to leave forwarding and `tailscaled`'s own rules working on this node. It is a second layer behind the policy and not a replacement, because `tailscaled` accepts everything that arrives on `tailscale0`, so the policy alone decides what a tailnet source reaches on the router's own services.
- A preference changed by hand on the node is drift that the next run repairs and `--check` shows.
- The join is verified on a real node and not in Molecule.
- A topic doc ([`network-infra.md`](../../topics/infra/network-infra.md)) describes the resulting behaviour once it exists.

## Invariants

- No Tailscale auth key or OAuth secret is in the repository, OpenBao, Tofu's state or a role default. A key exists only for the run that joins the node.
- A subnet router joins tagged, never as a user's device.
- The router keeps source NAT on while the gateway's rules identify tailnet callers by its address.
- Only apt updates Tailscale on a node.

## Non-goals

- The tailnet's policy, DNS and devices other than the node's own ([ADR 0059](../0059-where-the-tailnet-policy-is-defined/revision-000.md)).
- Exit nodes, Tailscale SSH, Serve and Funnel.
- Whether the GCP node joins the tailnet. It may use this role if it does, decided with its own project.
- Whether the Proxmox node's membership is configured by this role. [`proxmox-node-install.md`](../../projects/proxmox-node-install.md) decides that with its inventory of the node.

## Validation

The Molecule scenario for the role, and a `--check` run against the live node after every change to the role or its variables.

## Reconsideration triggers

- A published role or collection converges a node against its actual preferences and joins only when the node is logged out.
