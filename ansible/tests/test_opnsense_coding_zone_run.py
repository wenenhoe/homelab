"""The coding-zone scratch run agrees with the gateway play and the flow list it runs against.

The spec carries its own copy of the play's flows, with one row added, and names the addresses its controls and its source
depend on, so a change to the play or the flow list has to reach it or these fail."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
ADDED_ROW = {
    "name": "operator hosts to the coding-agent canary over SSH",
    "zones": ["desktops", "management"],
    "source": "operator_hosts",
    "destination": "net_coding",
    "protocol": "TCP",
    "port": "22",
}


@pytest.fixture(scope="module")
def defaults() -> dict:
    return yaml.safe_load((REPO / "ansible/roles/opnsense_gateway/defaults/main.yaml").read_text())


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load((REPO / "tofu/scratch/opnsense/runs/coding-zone.yaml").read_text())


@pytest.fixture(scope="module")
def flow_list() -> dict:
    return yaml.safe_load((REPO / "tools/network_checks/flows.yaml").read_text())


def flows_by_id(flow_list: dict) -> dict[str, dict]:
    return {flow["id"]: flow for flow in flow_list["flows"]}


def step(spec: dict, step_id: str) -> dict:
    return next(item for item in spec["steps"] if item["id"] == step_id)


def test_the_flows_are_the_plays_own_with_one_row_that_admits_the_operator_hosts_to_the_zone(spec, defaults):
    flows = spec["gateway"]["play_vars"]["opnsense_gateway_flows"]

    assert flows[:-1] == defaults["opnsense_gateway_flows"]
    assert flows[-1] == ADDED_ROW
    assert "scratch_wan" in flows[-2]  # the play's last flow is the scratch zone's, which a scratch run switches off


def test_the_added_row_is_the_only_flow_that_reaches_the_zones_canary(spec, defaults):
    flows = spec["gateway"]["play_vars"]["opnsense_gateway_flows"]

    assert [flow["name"] for flow in flows if flow["destination"] == "net_coding"] == [ADDED_ROW["name"]]
    assert not [flow for flow in defaults["opnsense_gateway_flows"] if flow["destination"] == "net_coding"]


def test_the_zones_canary_is_a_scratch_vm_on_a_gateway_seeded_with_the_zones_vlan(spec, defaults):
    zone = next(zone for zone in defaults["opnsense_gateway_zones"] if zone["name"] == "coding")

    assert spec["canary_vm"] == {"zone": "coding"}
    assert zone["vlan"] in spec["gateway"]["vlans"]
    assert {zone["vlan"] for zone in defaults["opnsense_gateway_zones"] if "scratch_wan" not in zone} <= set(spec["gateway"]["vlans"])


def test_the_operator_hosts_hold_the_runners_host_and_the_desktops_canary_and_not_the_zones_canary(spec, flow_list):
    hosts = spec["gateway"]["play_vars"]["opnsense_gateway_operator_hosts"]

    assert "192.168.40.250" in hosts
    assert flow_list["zones"]["desktops"]["canary"] in hosts
    assert flow_list["zones"]["coding"]["canary"] not in hosts


def test_every_deny_from_the_zone_is_tried_by_a_step_and_each_of_its_controls_is_an_allow(spec, flow_list):
    by_id = flows_by_id(flow_list)
    tried = set(step(spec, "coding-isolation")["flows"]["ids"]) | set(step(spec, "node-probe")["flows"]["ids"])
    from_the_zone = {flow_id for flow_id, flow in by_id.items() if flow["from"] == "coding" and flow["expect"] == "deny" and "scratch" not in flow_id}

    assert from_the_zone <= tried
    assert {by_id[by_id[flow_id]["control"]]["expect"] for flow_id in tried} == {"allow"}


def test_the_isolation_step_tries_each_other_zones_canary_against_the_zones_canary_except_the_one_the_added_row_admits(spec, flow_list):
    by_id = flows_by_id(flow_list)
    admitted = set(spec["gateway"]["play_vars"]["opnsense_gateway_operator_hosts"])
    into = {
        flow_id
        for flow_id, flow in by_id.items()
        if flow["to"]["address"] == flow_list["zones"]["coding"]["canary"] and flow["expect"] == "deny" and flow["from"] != "scratch"
    }
    tried = set(step(spec, "coding-isolation")["flows"]["ids"])

    assert into
    assert {flow_id for flow_id in into if flow_list["zones"][by_id[flow_id]["from"]]["canary"] in admitted} == {"desktops-to-coding-canary-denied"}
    assert into - tried == {"desktops-to-coding-canary-denied"}
    assert tried - into <= {flow_id for flow_id, flow in by_id.items() if flow["from"] == "coding"}


def test_the_node_probe_denies_come_from_the_zone_and_are_controlled_from_the_admitted_desktops_canary(spec, flow_list):
    by_id = flows_by_id(flow_list)
    ids = step(spec, "node-probe")["flows"]["ids"]
    node = yaml.safe_load((REPO / "ansible/roles/opnsense_gateway/defaults/main.yaml").read_text())["opnsense_gateway_hosts"]["host_proxmox_node"]

    assert ids
    for flow_id in ids:
        flow = by_id[flow_id]
        control = by_id[flow["control"]]
        assert (flow["from"], flow["expect"], flow["to"]["address"]) == ("coding", "deny", node)
        assert (control["from"], control["to"]) == ("desktops", flow["to"])
    assert {by_id[flow_id]["to"]["port"] for flow_id in ids} == {22, 8006}
