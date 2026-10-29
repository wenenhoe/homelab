"""The gateway role's zone list and the seed that creates the zones' interfaces must agree."""

from __future__ import annotations

import ipaddress
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tofu/modules/proxmox_opnsense_vm/seed"))

import patch_config  # noqa: E402 - the seed builder, imported by path


@pytest.fixture
def defaults() -> dict:
    return yaml.safe_load((REPO / "ansible/roles/opnsense_gateway/defaults/main.yaml").read_text())


def test_the_zones_are_the_vlans_the_seed_creates_in_the_order_it_creates_them(defaults):
    assert [zone["vlan"] for zone in defaults["opnsense_gateway_zones"]] == list(patch_config.DEFAULT_VLANS)


def test_each_zone_names_the_interface_the_seed_gives_its_vlan(defaults):
    assert [zone["interface"] for zone in defaults["opnsense_gateway_zones"]] == [f"opt{n}" for n in range(1, len(patch_config.DEFAULT_VLANS) + 1)]


def test_each_zone_name_can_be_part_of_an_alias_name(defaults):
    for zone in defaults["opnsense_gateway_zones"]:
        assert zone["name"].isidentifier()
        assert len(f"net_{zone['name']}") <= 32


def test_zone_names_and_vlans_are_distinct(defaults):
    zones = defaults["opnsense_gateway_zones"]

    assert len({zone["name"] for zone in zones}) == len(zones)
    assert len({zone["vlan"] for zone in zones}) == len(zones)


def test_the_cd_agent_zone_is_one_of_the_zones(defaults):
    assert defaults["opnsense_gateway_cd_agent_zone"] in {zone["name"] for zone in defaults["opnsense_gateway_zones"]}


def test_the_cd_agent_is_not_admitted_to_the_gateway_until_the_decision_allows_it(defaults):
    assert defaults["opnsense_gateway_cd_agent_management"] is False


def test_there_is_no_default_for_the_operator_hosts_because_an_empty_guard_admits_nobody(defaults):
    assert "opnsense_gateway_operator_hosts" not in defaults


def test_the_services_every_zone_asks_of_the_gateway_have_distinct_names(defaults):
    names = [service["name"] for service in defaults["opnsense_gateway_zone_services"]]

    assert len(set(names)) == len(names)


INVENTORY = REPO / "ansible/inventory"
FIXED_ALIASES = {"operator_hosts", "cd_agent_hosts"}


def address_of(defaults: dict, alias: str) -> str | None:
    """The address a host alias holds, the first of cd_agent_hosts, or None for a network or the operator hosts."""
    if alias in defaults["opnsense_gateway_hosts"]:
        return defaults["opnsense_gateway_hosts"][alias]
    if alias == "cd_agent_hosts":
        return defaults["opnsense_gateway_cd_agent_hosts"][0]
    return None


def zone_network(defaults: dict, alias: str) -> ipaddress.IPv4Network | None:
    for zone in defaults["opnsense_gateway_zones"]:
        if alias == f"net_{zone['name']}":
            return ipaddress.ip_network(f"192.168.{zone['vlan']}.0/24")
    return None


def test_the_sos_hosts_have_the_addresses_the_inventory_gives_them(defaults):
    inventory = yaml.safe_load((INVENTORY / "sos-inventory.yaml").read_text())["all"]["children"]["sos"]["hosts"]

    for name in ("tailscale", "services", "play", "security", "storage"):
        assert defaults["opnsense_gateway_hosts"][f"host_{name}"] == inventory[name]["ansible_host"]


def test_the_cd_agent_has_the_address_the_inventory_gives_it(defaults):
    inventory = yaml.safe_load((INVENTORY / "inventory.yaml").read_text())["all"]["children"]["cd_agent"]["hosts"]

    assert defaults["opnsense_gateway_cd_agent_hosts"] == [inventory["cd-agent"]["ansible_host"]]


def test_the_operator_host_302_is_the_address_the_cd_agent_trusts(defaults):
    group = yaml.safe_load((INVENTORY / "group_vars/cd_agent.yaml").read_text())

    assert defaults["opnsense_gateway_hosts"]["host_operator_302"] == group["cd_agent_operator_address"]


def test_the_proxmox_node_has_the_address_the_dns_records_give_it(defaults):
    records = yaml.safe_load((INVENTORY / "host_vars/services.yaml").read_text())
    pve = [r for zone in _walk_dns_records(records) for r in zone if r.get("name") == "pve"]

    assert {r["value"] for r in pve} == {defaults["opnsense_gateway_hosts"]["host_proxmox_node"]}


def _walk_dns_records(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk_dns_records(value)
    elif isinstance(node, list):
        if node and all(isinstance(item, dict) and "type" in item and "value" in item for item in node):
            yield node
        else:
            for item in node:
                yield from _walk_dns_records(item)


def test_every_flow_starts_in_zones_that_exist(defaults):
    known = {zone["name"] for zone in defaults["opnsense_gateway_zones"]}

    for flow in defaults["opnsense_gateway_flows"]:
        assert flow["zones"]
        assert set(flow["zones"]) <= known, flow["name"]


def test_every_flow_names_aliases_the_play_writes(defaults):
    known = FIXED_ALIASES | set(defaults["opnsense_gateway_hosts"]) | {f"net_{zone['name']}" for zone in defaults["opnsense_gateway_zones"]}

    for flow in defaults["opnsense_gateway_flows"]:
        assert flow["source"] in known, flow["name"]
        assert flow["destination"] in known, flow["name"]


def test_every_flow_port_is_a_number_or_the_port_alias_the_play_writes(defaults):
    for flow in defaults["opnsense_gateway_flows"]:
        assert flow["port"] == "proxmox_node_ports" or (isinstance(flow["port"], str) and flow["port"].isdigit()), flow["name"]


def test_a_flow_whose_source_is_known_starts_in_a_zone_that_holds_it(defaults):
    zones = {zone["name"]: ipaddress.ip_network(f"192.168.{zone['vlan']}.0/24") for zone in defaults["opnsense_gateway_zones"]}

    for flow in defaults["opnsense_gateway_flows"]:
        address = address_of(defaults, flow["source"])
        network = zone_network(defaults, flow["source"])
        if address:
            in_a_zone = any(ipaddress.ip_address(address) in zones[z] for z in flow["zones"])
        elif network:
            in_a_zone = any(network == zones[z] for z in flow["zones"])
        else:
            continue
        assert in_a_zone, f"{flow['name']}: the source is in none of {flow['zones']}"


def test_flow_names_are_distinct_because_the_play_matches_rules_by_name(defaults):
    names = [flow["name"] for flow in defaults["opnsense_gateway_flows"]]

    assert len(set(names)) == len(names)


def test_each_family_of_rules_fits_before_the_next_one_starts(defaults):
    sequences = defaults["opnsense_gateway_sequences"]
    order = ["guard", "cd_agent", "zone_services", "direct_dns", "flows", "internet"]

    assert [sequences[name] for name in order] == sorted(sequences[name] for name in order)
    assert sequences["zone_services"] + len(defaults["opnsense_gateway_zone_services"]) <= sequences["direct_dns"]
    assert sequences["flows"] + len(defaults["opnsense_gateway_flows"]) <= sequences["internet"]


def test_the_private_ranges_are_the_rfc1918_ones(defaults):
    assert sorted(defaults["opnsense_gateway_private_networks"]) == ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]


def test_every_zone_is_inside_the_private_ranges_so_no_zone_can_be_reached_through_the_internet_rule(defaults):
    private = [ipaddress.ip_network(n) for n in defaults["opnsense_gateway_private_networks"]]

    for zone in defaults["opnsense_gateway_zones"]:
        net = ipaddress.ip_network(f"192.168.{zone['vlan']}.0/24")
        assert any(net.subnet_of(p) for p in private), zone["name"]


def test_the_proxmox_node_is_inside_the_private_ranges_so_only_the_named_flow_reaches_it(defaults):
    node = ipaddress.ip_address(defaults["opnsense_gateway_hosts"]["host_proxmox_node"])

    assert any(node in ipaddress.ip_network(n) for n in defaults["opnsense_gateway_private_networks"])


def test_the_isolated_zone_has_no_internet_and_the_experimental_zone_has_it(defaults):
    internet = {zone["name"]: zone["internet"] for zone in defaults["opnsense_gateway_zones"]}

    assert internet["isolated"] is False
    assert internet["experimental"] is True


def test_the_seed_leaves_outbound_nat_automatic_so_the_play_writes_no_nat_rules():
    root = ET.parse(patch_config.BASE).getroot()  # noqa: S314 - the sample shipped beside the builder

    assert root.findtext("nat/outbound/mode") == "automatic"


def test_a_flow_that_rests_on_an_unconfirmed_decision_is_written_but_not_in_force(defaults):
    held_back = {flow["name"] for flow in defaults["opnsense_gateway_flows"] if flow.get("enabled") is False}

    assert held_back == {
        "operator hosts to storage for state and restores",
        "CD agent to the services zone over SSH",
        "CD agent to security for the secrets store",
        "CD agent to storage for the write key",
    }


def test_kea_serves_the_zones_whose_clients_tofu_does_not_place(defaults):
    dhcp = {zone["name"]: zone["dhcp"] for zone in defaults["opnsense_gateway_zones"]}

    assert dhcp == {"services": False, "others": False, "desktops": True, "isolated": True, "experimental": True}


def test_the_pool_leaves_the_low_and_high_addresses_to_reservations_and_the_gateway(defaults):
    pool = defaults["opnsense_gateway_dhcp_pool"]

    assert 2 <= pool["first"] <= pool["last"] <= 254


def test_there_are_no_reservations_by_default(defaults):
    assert defaults["opnsense_gateway_dhcp_reservations"] == []


def test_dnsmasq_is_turned_off_before_kea_is_turned_on_because_both_want_udp_port_67():
    tasks = yaml.safe_load((REPO / "ansible/roles/opnsense_gateway/tasks/dhcp.yaml").read_text())
    calls = [(key, task[key]) for task in tasks for key in task if key.startswith("oxlorg.opnsense.")]
    names = [name for name, _ in calls]

    assert names.index("oxlorg.opnsense.dnsmasq_general") < names.index("oxlorg.opnsense.dhcp_general")
    assert dict(calls)["oxlorg.opnsense.dnsmasq_general"]["enabled"] is False


def test_the_seed_s_sample_runs_dnsmasq_for_the_lan_which_is_what_the_play_turns_off():
    root = ET.parse(patch_config.BASE).getroot()  # noqa: S314 - the sample shipped beside the builder

    assert root.findtext("dnsmasq/enable") == "1"
