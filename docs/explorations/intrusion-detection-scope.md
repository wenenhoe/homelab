---
id: EXP-intrusion-detection-scope
title: "Where should intrusion detection run, and how much of the lab should it see?"
type: exploration
status: open
summary: "Whether detection lives only on the OPNsense perimeter or also on each VM, without inspecting the lab's own TLS."
topic: security-hardening
related: [ADR-0047, ADR-0053, ADR-0089, ADR-0094]
---

# Where should intrusion detection run, and how much of the lab should it see?

No intrusion detection or prevention exists anywhere in the repo. The
constraint going in is that it works without inline traffic inspection, so no
interception of the lab's own TLS. That rules out most inline-proxy designs and
points to log-based detection per node, such as CrowdSec: local detection with
decisions shared through a local API, outside the traffic path. OPNsense has a
maintained CrowdSec plugin that parses firewall and WAN logs and applies blocks
through pf. The open question is scope, not tooling.

## What bears on it

- **Perimeter only** puts CrowdSec on OPNsense alone, reading its own firewall
  and WAN logs. It catches scanning and brute-force patterns at the edge. It is
  blind to a request that looks fine at the firewall and is malicious at the
  application layer, such as valid HTTP requests to the reverse proxy.
- **Perimeter plus per-VM agents** adds an agent on every managed host reading
  its own auth and application logs (SSH, reverse-proxy access logs, container
  logs) and reporting to a central local API. Coverage is much richer. Each
  agent costs resources on its host and holds a fleet-wide credential, its key
  for that API. Delivering that key is the first-credential bootstrap problem
  of [ADR 0047](../decisions/0047-first-credential-bootstrap-for-automated-processes/revision-000.md),
  not a separate one.
- **OPNsense day-2 configuration is not automated.** Installing plugins and
  applying settings through its API is documented in
  [`vm-provisioning.md`](../topics/infra/vm-provisioning.md) as not yet built;
  provisioning covers the VM shell and a manual install. Perimeter CrowdSec
  would start as a manual install, in the same category as OPNsense today, and
  running it unmanaged is a small instance of load-bearing infrastructure that
  nothing manages. It is not confirmed that the plugin is usable before that
  automation exists.
- The gateway and boundary decisions
  ([ADR 0089](../decisions/0089-how-the-opnsense-gateway-is-configured/revision-000.md),
  [ADR 0094](../decisions/0094-showing-the-network-boundary-behaves-as-declared/revision-000.md))
  and the coding-agent host's network reach
  ([ADR 0053](../decisions/0053-network-reach-of-the-coding-agent-host/revision-000.md))
  all leave intrusion detection and traffic inspection out of scope.

## Options

1. **Perimeter only.** Lowest cost and no fleet credential. Misses
   application-layer attacks that pass the firewall.
2. **Perimeter plus agents.** Highest visibility. Real per-host cost, a new
   credential per agent, and the bootstrap question to answer first.
3. **No detection yet.** Wait for the gateway's day-2 configuration to be
   automated, so the plugin is not a manual install.

What has to be answered first is how much visibility is wanted. That is a
preference once someone is ready to decide, not a spike question.

## Leaning

None.
