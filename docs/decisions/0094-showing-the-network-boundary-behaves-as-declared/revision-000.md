---
id: ADR-0094
revision: 0
type: adr
title: Showing that the network boundary behaves as declared
short: Network boundary checks
solution: "One committed flow list drives a unit-tested runner that tries each flow from a canary VM in its source zone and reports through the job-heartbeat path"
summary: How the lab shows that the firewall policy between its zones allows the flows it declares and blocks the rest, before and after a change to the gateway and on a schedule.
topic: security-hardening
status: working
related: [ADR-0053, ADR-0058, ADR-0059, ADR-0064, ADR-0069, ADR-0072, ADR-0089]
---

# 0094. Showing that the network boundary behaves as declared

## Problem

The firewall policy between the lab's zones decides which flows work, and other decisions rest on it: [ADR 0053 (Coding-agent network reach)](../0053-network-reach-of-the-coding-agent-host/revision-000.md) states that the coding-agent VLAN has no path to the secrets store, the CD agent or the Proxmox management address. Nothing shows that such a statement holds. A rule set can read correctly in an export and not apply, a release change can alter how rules are evaluated, and a rebuilt gateway can differ from what a decision intended.

What has to be true: the flows the lab expects, allowed and blocked, are written once; each is tried from the zone it starts in, by something other than the host under test; a block is told apart from a destination that is down; the outcome is decided by tested code, not by reading output; and the check runs before and after a change to the gateway and on a schedule.

## Context

Three projects name canary probes, and none defines one: [`opnsense-config.md`](../../projects/opnsense-config.md) (the exit conditions of its Stages 3 and 4), [`coding-agent-egress.md`](../../projects/coding-agent-egress.md) (Stage 2: probes to the secrets store, CD agent, operator host, managed hosts, workstation and Proxmox management address all fail) and [`operator-host-takeover.md`](../../projects/operator-host-takeover.md) (Stage 1: a canary in VLAN 30 reaches every allowlisted destination and no other). ADR 0053's validation places the canary in the zone, outside the host, because a compromised host cannot be trusted to report on itself. [ADR 0089 (OPNsense configuration)](../0089-how-the-opnsense-gateway-is-configured/revision-000.md) lists smoke checks for a release change: a probe VM gets a lease and resolves names, NAT works, the API answers.

Facts recorded in ADR 0089 that shape a probe:

- A rule created through the API for one interface is placed after that interface's legacy rules, so a block can sit behind an allow and never apply. An export of the rule set shows the block; only an attempt shows that it does nothing.
- A block cut new connections and left open ones working. A probe has to open a new connection.
- A floating, quick pass rule from the management hosts to the management ports comes first in the ruleset. A probe from the operator host to those ports is allowed by design and cannot show a block.

Where a check can run from is limited. Gatus is deployed on `security` only ([`gatus.md`](../../topics/monitoring/gatus.md)), so its own checks start in one zone. A default-deny zone has no flow to another internal VLAN, so a canary there cannot push to Gatus. [ADR 0072 (Job heartbeats)](../0072-detecting-scheduled-jobs-that-stop-running/revision-000.md) already decides how a job that runs elsewhere is watched: it pushes on success, and a failed run reports through `OnFailure=`.

The play runs from the operator host and, until it is retired, VM 401 ([ADR 0089 (OPNsense configuration)](../0089-how-the-opnsense-gateway-is-configured/revision-000.md)). Repo logic that decides an outcome is unit-tested Python under `tools/`, one package per domain ([ADR 0064 (CI and doc check code)](../0064-where-the-code-behind-ci-and-documentation-checks-lives/revision-000.md), [ADR 0069 (Python test style)](../0069-how-python-unit-tests-are-written-and-run/revision-000.md)), and the catalog rules checks read a data file through one loader and run as pre-commit hooks ([`gates.md`](../../topics/engineering/ci/gates.md#secret-catalog-rules)).

Batfish's list of supported devices names no OPNsense or pfSense release.

## Decision

**One flow list.** A committed YAML file in a `network_checks` package under `tools/` is the only place the expected flows are written for checking. It declares the zones (a name and a subnet), one canary per zone, and the flows:

| Field | Meaning |
| :--- | :--- |
| `id` | Unique name of the flow |
| `from` | The source zone, whose canary makes the attempt |
| `to` | The destination address or name, with port and protocol |
| `kind` | `connect` (a TCP connection is established) or `dns` (a query is answered) |
| `expect` | `allow` or `deny` |
| `control` | A deny only: the `id` of an allow flow to the same destination and port |
| `tags` | Free labels; `smoke` marks the flows a release rehearsal runs |

The list says what is intended. It is not the source of the gateway's rules, which carry ordering, floating and per-interface scope that a flow does not.

**Probes run from canaries.** A canary is a small VM in a zone, provisioned like any other VM and outside every host under test. It holds no credential, repository checkout or flow list. The runner, on the host that runs the play, reaches the canary over SSH, sends a standard-library-only Python module on standard input to the canary's `python3`, and reads one JSON result per probe back. Nothing is installed on the canary. Each probe opens a new connection.

**Reading a result.** An allow flow passes when the attempt succeeds. A deny flow passes only when the attempt fails and its control passed in the same run; a deny whose control failed is reported as failed, since the destination or the canary may simply be down. Every canary has at least one allow flow, so a dead canary cannot make its denies pass. A probe the runner could not run counts as failed.

**Rules the loader enforces.** Ids are unique; every zone named exists and has a canary and an allow flow; a deny's control is an allow flow to the same destination and port; and every ordered pair of declared zones has at least one flow, so a default-deny is stated, not assumed. The loader refuses a file that breaks one, runs as a pre-commit hook like the catalog rules checks, and has a failing case per rule in its unit tests.

**When it runs.** Against a scratch gateway or a clone during development; as the release rehearsal's smoke checks, on the flows tagged `smoke`; after each apply to the gateway; and on a schedule against production. The run exits zero only if every selected probe passes. A fully passing scheduled run pushes the job's heartbeat from the runner's host, never from a canary; a failing run exits non-zero so the unit's `OnFailure=` alerts, as ADR 0072 decides for any job. How the run is started (a timer on the operator host, later a CD agent job) is decided where that host and agent are. State checks such as a valid WAN gateway or VLANs being up stay in the rehearsal and are not flows.

## Alternatives considered

- **Batfish.** It analyses configuration offline, but its supported devices include no OPNsense, so there is nothing to feed it.
- **Generating the gateway's rules from the flow list.** One statement, no drift between list and play. It loses because the ordering, floating and per-interface effects ADR 0089 records would move into a generator, and its output would still need probes to show it applies.
- **Comparing an export of the rule set**, as ADR 0053 does against its topic doc. It shows the rules, not their effect: a block behind a legacy allow exports correctly and applies to nothing. It stays as a complement.
- **Probes from the operator host alone.** They start in one zone, and the management guard rule keeps that host's path to the management ports open, so they cannot show a block there.
- **Gatus's own checks.** Gatus runs in one zone, and the flows to test start in several.
- **A resident agent on each canary that pushes results.** A default-deny zone cannot reach Gatus, and the agent would hold a push token and code on a host in a zone the decisions treat as untrusted.
- **Behave or another Gherkin runner.** A second runner and language for what is a table of rows, against the one test style of ADR 0069.
- **Crafted packets.** A connection and a DNS query test what the lab relies on. Fragmentation and malformed traffic are outside that.

## Assumptions

- **Claim:** the runner's host can reach each canary over SSH under the rules the zones' decisions already admit.
  **Breaks if wrong:** a zone's decision needs a revision to admit the runner's host to the canary, or the run needs a canary-side scheduler that the runner reads from, which ADR 0053's inbound rule does not allow today.
  **Checked by:** reading ADR 0053 and ADR 0058's inbound rules, then a scratch-zone attempt.
- **Claim:** TCP connect and DNS query cover the flows the three projects name, apart from requests through the egress proxy, which the project that builds the proxy adds as a kind.
  **Breaks if wrong:** another kind is added to the schema, with probe code and tests of its own.
  **Checked by:** reading the flows the policy stage lists for the existing zones.

## Consequences

- A small VM per zone under test, on a node with limited headroom.
- A pass shows the listed flows at the time of the run. A flow not listed is not tried, and the zone-pair rule covers pairs, not ports.
- A run cannot see a session that was open before a change, only the new connections it opens.
- The list is a third statement of intent beside the play and the topic doc. Probes are what ties it to the play.
- The runner needs SSH to every canary, which is an inbound flow in each zone that the zone's decision has to admit.
- A topic doc will describe the resulting behaviour once it exists.

## Invariants

- The expected flows are written in the flow list and nowhere else; no probe is defined in a workflow, role or script.
- Every deny has a control, and every canary has an allow flow.
- A probe opens a new connection.
- A canary holds no credential, repository checkout or flow list.
- A probe the runner could not run is a failed probe, and a run exits zero only if every selected probe passed.
- The heartbeat is pushed by the runner's host, after a fully passing run.

## Non-goals

- The firewall rules, and which flows each zone needs: the decisions that need them state those.
- Throughput, latency and the gateway's state.
- How `--check --diff` output is read as drift on the gateway. That depends on the collection's real output and is its own lineage.
- The tailnet policy's own `tests` ([ADR 0059 (Tailnet policy)](../0059-where-the-tailnet-policy-is-defined/revision-000.md)), which assert grants, not gateway behaviour.
- Inspecting traffic content ([ADR 0039 (Intrusion detection scope)](../0039-intrusion-detection-scope/revision-000.md)).

## Validation

Unit tests cover each loader rule and the runner against a fake canary. On a scratch gateway, removing a rule that an allow flow depends on must make that probe fail, which shows the harness can catch the failure it exists for. A scheduled run's heartbeat and its `OnFailure=` alert are shown by a deliberately failing flow.

## Reconsideration triggers

- The operator host cannot reach a canary without breaking a zone's invariant.
- A flow needs richer traffic than a connection or a DNS query.
- A second enforcement layer, such as the Proxmox firewall ADR 0089 keeps as a possible one, makes a failed probe ambiguous about which layer blocked it.
- The gateway's rule evaluation becomes simple enough that generating its rules from the list no longer hides behaviour.
