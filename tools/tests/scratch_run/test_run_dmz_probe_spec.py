"""Tests that the dmz-probe spec agrees with the gateway play and the flow list it runs against.

The spec carries its own copy of the play's flows, with one row added, and names the addresses its control and its source
depend on, so a change to the play or the flow list has to reach it or these fail.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

import pytest
import yaml
from network_checks.flow_list import FlowList, load_flow_list
from scratch_run.spec import Spec, load_spec
from scratch_run_fakes import RUNS

REPO = Path(__file__).resolve().parents[3]
DEFAULTS = yaml.safe_load((REPO / "ansible/roles/opnsense_gateway/defaults/main.yaml").read_text())


@pytest.fixture(scope="module")
def spec() -> Spec:
    return load_spec(RUNS / "dmz-probe.yaml")


@pytest.fixture(scope="module")
def flow_list() -> FlowList:
    return load_flow_list()


def test_the_seed_list_holds_the_vlan_of_every_zone_of_the_play(spec):
    assert {zone["vlan"] for zone in DEFAULTS["opnsense_gateway_zones"] if "scratch_wan" not in zone} <= set(spec.vlans)


def test_the_flows_are_the_plays_own_with_one_row_that_admits_the_operator_hosts_to_the_dmz(spec):
    flows = spec.play_vars["opnsense_gateway_flows"]

    assert flows[:-1] == DEFAULTS["opnsense_gateway_flows"]
    assert flows[-1] == {
        "name": "operator hosts to the DMZ canary over SSH",
        "zones": ["desktops", "management"],
        "source": "operator_hosts",
        "destination": "net_dmz",
        "protocol": "TCP",
        "port": "22",
    }


def test_the_operator_hosts_hold_the_runners_host_and_the_desktops_canary_and_not_the_dmz_canary(spec, flow_list):
    hosts = spec.play_vars["opnsense_gateway_operator_hosts"]

    assert "192.168.40.250" in hosts
    assert str(flow_list.zones["desktops"].canary) in hosts
    assert str(flow_list.zones["dmz"].canary) not in hosts


def test_the_node_probe_denies_come_from_the_dmz_and_are_controlled_from_the_admitted_desktops_canary(spec, flow_list):
    by_id = {flow.id: flow for flow in flow_list.flows}
    probe = next(step for step in spec.steps if step.id == "node-probe")
    node = ipaddress.ip_address(DEFAULTS["opnsense_gateway_hosts"]["host_proxmox_node"])

    assert probe.flow_ids
    for flow_id in probe.flow_ids:
        flow = by_id[flow_id]
        control = by_id[flow.control]
        assert (flow.source, flow.expect, flow.destination.ip()) == ("dmz", "deny", node)
        assert (control.source, control.destination) == ("desktops", flow.destination)
    assert {by_id[flow_id].destination.port for flow_id in probe.flow_ids} == {22, 8006}


def test_the_dmz_isolation_step_leaves_out_the_pair_the_added_row_admits(spec, flow_list):
    by_id = {flow.id: flow for flow in flow_list.flows}
    isolation = next(step for step in spec.steps if step.id == "dmz-isolation")
    admitted = set(spec.play_vars["opnsense_gateway_operator_hosts"])

    for flow_id in isolation.flow_ids:
        assert str(flow_list.zones[by_id[flow_id].source].canary) not in admitted, flow_id
