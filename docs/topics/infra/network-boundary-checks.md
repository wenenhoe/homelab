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
