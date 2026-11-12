# Network boundary checks

How the lab states which flows between its zones are expected, so a check can show that the firewall allows them and blocks the rest ([ADR 0094](../../decisions/0094-showing-the-network-boundary-behaves-as-declared/revision-000.md)).

## The flow list

[`tools/network_checks/flows.yaml`](../../../tools/network_checks/flows.yaml) is the only place the expected flows are written for checking. It is a statement of intent, not the source of the gateway's rules, which carry ordering and per-interface scope that a flow does not.

It declares the zones, each with a subnet and one canary address inside it, and the flows:

| Field | Meaning |
| :--- | :--- |
| `id` | Unique name of the flow |
| `from` | The source zone, whose canary makes the attempt |
| `to` | `address` (an IPv4 address or a name), and `port` and `protocol` unless the kind is `ping` |
| `kind` | `connect` (a TCP connection is established), `dns` (a query is answered), `ping` (an ICMP echo is answered) or `ntp` (an SNTP query is answered) |
| `query` | A `dns` flow only, and required there: the name the query asks for |
| `expect` | `allow` or `deny` |
| `control` | A deny only, and required there: the `id` of an allow flow to the same destination, port and kind |
| `tags` | Free labels; `smoke` marks the flows a release rehearsal runs |

The protocol defaults to `tcp` for `connect` and `udp` for `ntp`; a `dns` flow says `udp` or `tcp`.

## What the loader and rules enforce

`network_checks.flow_list` refuses a file whose shape is wrong, and `network_checks.rules` refuses one that contradicts itself: ids are unique; every flow comes from a declared zone; every zone has an allow flow from its canary, so a dead canary cannot make its denies pass; a deny's control is an allow flow to the same destination, port and kind; and every ordered pair of declared zones has at least one flow, so a default-deny is stated and not assumed. The `check-flow-list` hook runs both ([`gates.md`](../engineering/ci/gates.md#flow-list-rules)).

## The probe module and the runner

A canary is a small VM in a zone, outside every host under test. It holds no credential, repository checkout or flow list, and nothing is installed on it beyond `python3` and, for a `ping` flow, `ping`. [`probe.py`](../../../tools/network_checks/probe.py) is the module that tries a flow. It uses the standard library only, because the runner sends it on the standard input of the canary's `python3` with the flows to try as one JSON argument, and reads one JSON result per flow back.

Each flow is tried once, on a new connection, since a rule that cuts new connections leaves open ones working. A result is one of three statuses:

| Status | Meaning |
| :--- | :--- |
| `ok` | The attempt succeeded: a connection was made, a query answered, an echo replied to |
| `failed` | The attempt did not: refused, silent or unreachable |
| `error` | The probe could not be run, for example because the canary has no `ping` |

[`runner.py`](../../../tools/network_checks/runner.py) runs from the host that runs the play:

```sh
cd tools
python -m network_checks.runner --ssh-user USER [--ssh-command "ssh -i KEY -o BatchMode=yes"] [--tag smoke] [--flow ID]
```

It refuses a flow list that breaks a rule, selects the flows by tag or id (all when neither is given) and adds the control of each selected deny. It opens one SSH session to the canary of each source zone in the selection and decides each flow:

- An allow flow passes when its attempt succeeded.
- A deny flow passes only when its attempt failed and its control passed in the same run, since the destination or the canary may simply be down. A deny whose control failed is reported as failed.
- A probe that could not be run, a session that failed or timed out, and a flow with no result all count as failed, whether the flow is an allow or a deny.

The exit status is zero only if every flow in the run passed. A selection that holds no flow exits 2 and passes nothing.

## The flows in the list

The list declares the five zones of the gateway's play, each with a canary at host part 08 of its subnet (`192.168.20.8` for services, `.30.8` for others, and so on). The Tofu canary VMs sit at those addresses ([`ubuntu-vms.md`](tofu/ubuntu-vms.md#canary-vms)), and tests fail when the zones differ from the play's or a canary's VMID from the list. It holds these flows:

| Flows | From | What they show |
| :--- | :--- | :--- |
| `<zone>-gateway-dns`, `-ntp`, `-ping` | Every zone | The gateway's address in the canary's own zone answers a query for `example.com`, a time request and an echo. These are the `smoke` flows |
| `<zone>-canary-ssh` | Every zone | The canary reaches itself on 22. It is the control for the denies aimed at that canary |
| `<zone>-internet-https`, `isolated-internet-denied` | Every zone | Port 443 on an outside address connects from every zone that has Internet, and not from the isolated zone |
| `<from>-to-<to>-canary-denied` | Every ordered pair of zones | No canary reaches another zone's canary on 22: the default-deny between zones, stated for each pair |
| `services-security-vault`, `<zone>-to-security-vault-denied` | Services, then the other four | The secrets store's port connects from inside its own zone and from no other zone's canary |

A flow carries its source zone as a tag, so `--tag services` runs the flows of the services canary alone. A deny whose control is tried from another zone's canary is tagged `cross-zone` and runs only once both canaries exist.

What the list does not hold yet:

- **Direct DNS to an outside resolver, and the gateway's management ports.** A deny needs a control to the same destination, port and kind, and these are blocked for every canary, so no control can pass. Showing them needs a rule that ADR 0094 does not state.
- **The desktops zone's flows to `play` on 25565 and to `services` on 1688.** They pass only while something listens there.
- **Flows from the operator host, the CD agent and the tailscale router.** A canary is not any of those hosts, so those rules are shown only by the denies above, not by an allow.
