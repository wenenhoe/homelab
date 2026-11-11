#!/usr/bin/env python3
"""Checks the rules of the flow list that its shape cannot (ADR 0094).

A list that passes the loader can still contradict itself: two flows with one id, a flow from a zone nobody
declared, a zone whose canary has no allow flow (so a dead canary would make every deny from it pass), a deny whose
control tries something else, or a pair of zones that no flow covers, which would leave a default-deny assumed and
not stated. Each violation is reported with the flow or zone and the rule it breaks; any violation fails the check.

Runs in pre-commit (PyYAML only).

Usage (from tools/): python -m network_checks.rules
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass

from network_checks.flow_list import FLOWS_PATH, Destination, Flow, FlowList, FlowListError, load_flow_list


@dataclass(frozen=True)
class Violation:
    name: str
    rule: str
    message: str


def destination_zone(flow_list: FlowList, destination: Destination) -> str | None:
    """The zone whose subnet holds the destination's address, or none for a name or an address outside every zone."""
    ip = destination.ip()
    if ip is None:
        return None
    return next((name for name, zone in flow_list.zones.items() if ip in zone.subnet), None)


def _same_target(flow: Flow, control: Flow) -> bool:
    return flow.destination == control.destination and flow.kind == control.kind


def check(flow_list: FlowList) -> list[Violation]:
    """Every rule the flow list breaks, in the order the rules are listed in the decision."""
    violations = []
    for flow_id, count in Counter(flow.id for flow in flow_list.flows).items():
        if count > 1:
            violations.append(Violation(flow_id, "unique-ids", f"{count} flows have this id"))
    for flow in flow_list.flows:
        if flow.source not in flow_list.zones:
            violations.append(Violation(flow.id, "known-zone", f"comes from `{flow.source}`, which is not a declared zone"))
    for name in flow_list.zones:
        if not any(flow.source == name and flow.expect == "allow" for flow in flow_list.flows):
            violations.append(Violation(name, "zone-allow", "has no allow flow from its canary, so a dead canary would make its denies pass"))
    allows = {flow.id: flow for flow in flow_list.flows if flow.expect == "allow"}
    for flow in flow_list.flows:
        if flow.expect != "deny" or flow.control is None:
            continue
        control = allows.get(flow.control)
        if control is None:
            violations.append(Violation(flow.id, "control-is-allow", f"names the control `{flow.control}`, which is not an allow flow"))
        elif not _same_target(flow, control):
            violations.append(
                Violation(flow.id, "control-same-target", f"names the control `{flow.control}`, which tries a different destination, port or kind")
            )
    reached = {(flow.source, destination_zone(flow_list, flow.destination)) for flow in flow_list.flows}
    for source in flow_list.zones:
        for target in flow_list.zones:
            if source != target and (source, target) not in reached:
                violations.append(Violation(f"{source} -> {target}", "pair-covered", "has no flow, so its default-deny is assumed and not stated"))
    return violations


def main() -> int:
    try:
        flow_list = load_flow_list(FLOWS_PATH)
    except FlowListError as exc:
        for problem in exc.problems:
            print(f"{FLOWS_PATH.name}: {problem}", file=sys.stderr)
        return 1
    violations = check(flow_list)
    for violation in violations:
        print(f"{FLOWS_PATH.name}: {violation.name}: [{violation.rule}] {violation.message}", file=sys.stderr)
    if violations:
        return 1
    print(f"Flow list OK: {len(flow_list.zones)} zones, {len(flow_list.flows)} flows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
