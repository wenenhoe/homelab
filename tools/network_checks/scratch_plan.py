"""The plan `scratch_canaries` builds a scratch gateway's zone hosts from, written from the flow list and the gateway's play.

    python -m network_checks.scratch_plan [--runner-address 192.168.40.250] [--runner-mac MAC] > plan.json

A zone's stand-in hosts are the addresses its inside holds that a `connect` flow aims at: a service of the lab that the
scratch gateway has no real host for. The gateway's own address, the canary and addresses outside every zone are not
stand-ins. The runner's host sits in the zone its address belongs to, with a fixed MAC so the gateway's ARP table cannot hide a block.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from pathlib import Path

import yaml

from network_checks.flow_list import FLOWS_PATH, FlowList, load_flow_list

GATEWAY_DEFAULTS = Path(__file__).resolve().parents[2] / "ansible" / "roles" / "opnsense_gateway" / "defaults" / "main.yaml"
RUNNER_ADDRESS = "192.168.40.250"
RUNNER_MAC = "bc:24:11:00:01:91"


def zone_vlans(path: Path = GATEWAY_DEFAULTS) -> dict[str, int]:
    return {zone["name"]: zone["vlan"] for zone in yaml.safe_load(path.read_text())["opnsense_gateway_zones"]}


def build_plan(flow_list: FlowList, vlans: dict[str, int], runner_address: str = RUNNER_ADDRESS, runner_mac: str = RUNNER_MAC) -> dict:
    """The zones with their canary, gateway and stand-in hosts, and the runner's host."""
    runner = ipaddress.IPv4Address(runner_address)
    zones = []
    runner_zone = None
    for name, zone in flow_list.zones.items():
        gateway = zone.subnet.network_address + 1
        stand_ins = sorted(
            {
                (str(flow.destination.ip()), flow.destination.port)
                for flow in flow_list.flows
                if flow.kind == "connect" and flow.destination.ip() in zone.subnet and flow.destination.ip() not in (gateway, zone.canary)
            }
        )
        zones.append(
            {
                "name": name,
                "vlan": vlans[name],
                "gateway": str(gateway),
                "canary": str(zone.canary),
                "listeners": [{"address": address, "port": port} for address, port in stand_ins],
            }
        )
        if runner in zone.subnet:
            runner_zone = zones[-1]
    if runner_zone is None:
        raise ValueError(f"the runner's address {runner_address} is in no zone of the flow list")
    return {"zones": zones, "runner": {"address": runner_address, "mac": runner_mac, "vlan": runner_zone["vlan"], "gateway": runner_zone["gateway"]}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--runner-address", default=RUNNER_ADDRESS)
    parser.add_argument("--runner-mac", default=RUNNER_MAC)
    parser.add_argument("--flows", type=Path, default=FLOWS_PATH)
    args = parser.parse_args(argv)
    print(json.dumps(build_plan(load_flow_list(args.flows), zone_vlans(), args.runner_address, args.runner_mac), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
