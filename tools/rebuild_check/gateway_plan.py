#!/usr/bin/env python3
"""Read what a Tofu plan of the root module says about the production gateway.

`tofu show -json PLAN` is the input. The gateway's preflight asks two things of it: whether the plan holds
the changes the stage expects, and what a variable's value is. Nothing here runs Tofu or touches the node.

Usage:
    python3 -m rebuild_check.gateway_plan verdict before|create PLAN.json
    python3 -m rebuild_check.gateway_plan variable NAME PLAN.json

`verdict before` passes when the plan changes nothing: the gateway is still the VM Tofu's state holds, and
every other resource matches the code. `verdict create` passes when the plan adds the gateway VM and its seed
file and changes nothing else, the state after the old VM is destroyed. Both print what differs and exit 1
otherwise. `variable` prints the value of a root variable and exits 1 when the plan has none by that name.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

GATEWAY_VM = "module.opnsense.proxmox_virtual_environment_vm.this"
GATEWAY_SEED = "module.opnsense.proxmox_virtual_environment_file.seed[0]"
# What a plan's `actions` hold for a resource it leaves alone or only reads.
UNCHANGED = ({"no-op"}, {"read"})


def changes(plan: dict) -> dict[str, list[str]]:
    """Each address the plan would change, with its actions (`["create"]`, `["delete", "create"]`)."""
    found: dict[str, list[str]] = {}
    for resource in plan.get("resource_changes", []):
        actions = resource["change"]["actions"]
        if set(actions) not in UNCHANGED:
            found[resource["address"]] = actions
    return found


def describe(found: dict[str, list[str]]) -> str:
    return ", ".join(f"{address} ({'+'.join(actions)})" for address, actions in sorted(found.items()))


def verdict(plan: dict, stage: str) -> tuple[bool, str]:
    found = changes(plan)
    if stage == "before":
        if not found:
            return True, "the plan changes nothing"
        return False, f"the plan changes: {describe(found)}"
    expected = {GATEWAY_VM: ["create"], GATEWAY_SEED: ["create"]}
    if found == expected:
        return True, "the plan adds the gateway VM and its seed file and nothing else"
    return False, f"expected only the gateway VM and its seed file to be added, the plan has: {describe(found) or 'no change'}"


def variable(plan: dict, name: str) -> str | None:
    value = plan.get("variables", {}).get(name, {}).get("value")
    return None if value is None else str(value)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    usage = "usage: python3 -m rebuild_check.gateway_plan verdict before|create PLAN.json | variable NAME PLAN.json"
    if len(args) != 3 or args[0] not in ("verdict", "variable") or (args[0] == "verdict" and args[1] not in ("before", "create")):
        print(usage, file=sys.stderr)
        return 2
    plan = json.loads(Path(args[2]).read_text())
    if args[0] == "variable":
        value = variable(plan, args[1])
        if value is None:
            print(f"the plan has no variable {args[1]}", file=sys.stderr)
            return 1
        print(value)
        return 0
    ok, message = verdict(plan, args[1])
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
