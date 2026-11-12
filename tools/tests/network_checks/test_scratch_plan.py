"""Tests for the plan a scratch gateway's zone hosts are built from.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import json

import pytest
import yaml
from network_checks import scratch_plan
from network_checks.flow_list import FLOWS_PATH, load_flow_list
from stand_in_flows import FLOWS, VLANS


class TestPlan:
    def test_the_committed_flow_list_gets_a_plan_for_every_zone(self):
        plan = scratch_plan.build_plan(load_flow_list(FLOWS_PATH), scratch_plan.zone_vlans())

        assert [zone["name"] for zone in plan["zones"]] == list(load_flow_list(FLOWS_PATH).zones)
        assert all(zone["gateway"].endswith(".1") and zone["canary"].endswith(".8") for zone in plan["zones"])

    def test_a_service_the_flows_reach_in_a_zone_becomes_a_stand_in_host_there(self, flows_path):
        plan = scratch_plan.build_plan(load_flow_list(flows_path), VLANS)

        assert {zone["name"]: zone["listeners"] for zone in plan["zones"]} == {
            "services": [{"address": "192.168.20.5", "port": 8200}],
            "desktops": [],
        }

    def test_the_gateway_the_canary_and_outside_addresses_are_not_stand_in_hosts(self, flows_path):
        flows = json.loads(json.dumps(FLOWS))
        flows["flows"] += [
            {"id": "services-dns", "from": "services", "to": {"address": "192.168.20.1", "port": 22}, "kind": "connect", "expect": "allow"},
            {"id": "services-internet", "from": "services", "to": {"address": "1.1.1.1", "port": 443}, "kind": "connect", "expect": "allow"},
        ]
        path = flows_path.with_name("more.yaml")
        path.write_text(yaml.safe_dump(flows))

        plan = scratch_plan.build_plan(load_flow_list(path), VLANS)

        assert [item["address"] for zone in plan["zones"] for item in zone["listeners"]] == ["192.168.20.5"]

    def test_the_runner_sits_in_the_zone_its_address_belongs_to(self, flows_path):
        plan = scratch_plan.build_plan(load_flow_list(flows_path), VLANS, "192.168.40.250", "02:aa:bb:cc:dd:ee")

        assert plan["runner"] == {"address": "192.168.40.250", "mac": "02:aa:bb:cc:dd:ee", "vlan": 40, "gateway": "192.168.40.1"}

    def test_a_runner_address_outside_every_zone_is_refused(self, flows_path):
        with pytest.raises(ValueError, match="in no zone"):
            scratch_plan.build_plan(load_flow_list(flows_path), VLANS, "10.9.9.9")
