"""Tests that the committed flow list agrees with the files that build what it describes.

The canary VMs' addresses come from the Tofu VMID scheme and the zones from the gateway's play, so a change to either has to
reach the flow list or these fail.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

import pytest
import yaml
from network_checks.flow_list import FLOWS_PATH, FlowList, load_flow_list

REPO = Path(__file__).resolve().parents[3]
CANARIES_TF = REPO / "tofu" / "canaries.tf"
GATEWAY_DEFAULTS = REPO / "ansible" / "roles" / "opnsense_gateway" / "defaults" / "main.yaml"


@pytest.fixture(scope="module")
def flow_list() -> FlowList:
    return load_flow_list(FLOWS_PATH)


def test_every_zone_is_a_zone_of_the_gateways_play(flow_list):
    play = yaml.safe_load(GATEWAY_DEFAULTS.read_text())["opnsense_gateway_zones"]

    assert {name: str(zone.subnet) for name, zone in flow_list.zones.items()} == {zone["name"]: f"192.168.{zone['vlan']}.0/24" for zone in play}


def test_every_canary_is_at_host_part_08_of_its_zone(flow_list):
    assert {name: zone.canary for name, zone in flow_list.zones.items()} == {name: zone.subnet.network_address + 8 for name, zone in flow_list.zones.items()}


def test_the_tofu_canaries_sit_at_the_addresses_the_flow_list_declares(flow_list):
    block = re.search(r"canary_vm_ids = \{(.*?)\}", CANARIES_TF.read_text(), re.DOTALL)
    assert block is not None
    vm_ids = {name: int(vm_id) for name, vm_id in re.findall(r"(\w+)\s*=\s*(\d+)", block.group(1))}

    assert vm_ids
    for name, vm_id in vm_ids.items():
        vlan, host = divmod(vm_id, 100)
        assert flow_list.zones[name].canary == ipaddress.IPv4Address(f"192.168.{vlan * 10}.{host}")


def test_a_flow_tagged_with_a_zone_is_tried_from_that_zone(flow_list):
    tagged = [flow for flow in flow_list.flows for tag in flow.tags if tag in flow_list.zones and tag != flow.source]

    assert tagged == []


def test_a_deny_with_a_control_from_its_own_zone_is_not_tagged_cross_zone(flow_list):
    by_id = {flow.id: flow for flow in flow_list.flows}
    wrong = [flow.id for flow in flow_list.flows if flow.control is not None and (by_id[flow.control].source == flow.source) == ("cross-zone" in flow.tags)]

    assert wrong == []


def test_the_smoke_flows_come_from_every_zone(flow_list):
    assert {flow.source for flow in flow_list.flows if "smoke" in flow.tags} == set(flow_list.zones)


def test_a_flow_that_needs_a_service_listening_carries_the_listener_tag(flow_list):
    needs_listener = {("192.168.20.4", 25565), ("192.168.20.3", 1688)}
    flows = [flow for flow in flow_list.flows if flow.destination.port is not None and (str(flow.destination.address), flow.destination.port) in needs_listener]

    assert flows
    assert [flow.id for flow in flows if "listener" not in flow.tags] == []
