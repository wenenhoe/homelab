"""The gateway role's zone list and the seed that creates the zones' interfaces must agree.

The seed may carry VLANs that have no zone; the play does not touch their interfaces."""

from __future__ import annotations

import ipaddress
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tofu/modules/proxmox_opnsense_vm/seed"))

import patch_config  # noqa: E402 - the seed builder, imported by path


@pytest.fixture
def defaults() -> dict:
    return yaml.safe_load((REPO / "ansible/roles/opnsense_gateway/defaults/main.yaml").read_text())


def test_every_zone_is_a_vlan_the_seed_creates_and_none_is_listed_twice(defaults):
    vlans = [zone["vlan"] for zone in defaults["opnsense_gateway_zones"]]

    assert set(vlans) <= set(patch_config.DEFAULT_VLANS)
    assert len(set(vlans)) == len(vlans)


def test_each_zone_names_the_interface_the_seed_gives_its_vlan(defaults):
    zones = defaults["opnsense_gateway_zones"]

    assert [zone["interface"] for zone in zones] == [f"opt{patch_config.DEFAULT_VLANS.index(zone['vlan']) + 1}" for zone in zones]


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


def test_the_operator_host_252_is_the_address_the_cd_agent_trusts(defaults):
    group = yaml.safe_load((INVENTORY / "group_vars/cd_agent.yaml").read_text())

    assert defaults["opnsense_gateway_hosts"]["host_operator_252"] == group["cd_agent_operator_address"]


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

    assert dhcp == {
        "services": False,
        "management": False,
        "desktops": True,
        "isolated": True,
        "experimental": True,
        "dmz": False,
        "coding": False,
        "scratch": True,
    }


def test_each_kea_scope_offers_the_zones_gateway_as_router_and_as_resolver_where_the_zone_may_use_it(defaults):
    tasks = yaml.safe_load((REPO / "ansible/roles/opnsense_gateway/tasks/dhcp.yaml").read_text())
    scope = next(task for task in tasks if "oxlorg.opnsense.dhcp_subnet" in task)
    args = scope["oxlorg.opnsense.dhcp_subnet"]
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)  # noqa: S701 - renders task values, not HTML
    env.filters["bool"] = bool

    def offered(zone: dict, key: str):
        context = {"opnsense_gateway_zone": zone}
        context["opnsense_gateway_zone_prefix"] = env.from_string(scope["vars"]["opnsense_gateway_zone_prefix"]).render(context)
        value = args[key]
        return yaml.safe_load(env.from_string(value).render(context)) if isinstance(value, str) else [env.from_string(item).render(context) for item in value]

    assert args["auto_options"] is False
    for zone in (zone for zone in defaults["opnsense_gateway_zones"] if zone["dhcp"]):
        gateway = f"192.168.{zone['vlan']}.1"
        assert offered(zone, "gateway") == [gateway]
        assert offered(zone, "dns") == ([gateway] if zone["gateway_dns"] else [])
    assert offered({"vlan": 30, "gateway_dns": False}, "dns") == []


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


def test_the_forward_servers_are_the_hosts_the_inventory_gives_the_internal_zones(defaults):
    inventory = yaml.safe_load((REPO / "ansible/inventory/group_vars/all/main.yaml").read_text())

    assert defaults["opnsense_gateway_forward_servers"] == [inventory["dns_primary_address"], inventory["dns_secondary_address"]]
    assert defaults["opnsense_gateway_forward_servers"] == [
        defaults["opnsense_gateway_hosts"]["host_services"],
        defaults["opnsense_gateway_hosts"]["host_storage"],
    ]


def test_there_is_no_default_for_the_forwarded_zones_because_they_derive_from_a_secret(defaults):
    assert "opnsense_gateway_forward_domains" not in defaults


def test_the_forwards_are_written_before_the_ones_the_play_does_not_write_are_removed():
    tasks = yaml.safe_load((REPO / "ansible/roles/opnsense_gateway/tasks/forwards.yaml").read_text())
    calls = [(key, task[key]) for task in tasks for key in task if key.startswith("oxlorg.opnsense.")]

    assert [name for name, _ in calls] == ["oxlorg.opnsense.unbound_forward", "oxlorg.opnsense.list", "oxlorg.opnsense.unbound_forward"]
    assert calls[0][1].get("state", "present") == "present"
    assert calls[2][1]["state"] == "absent"
    assert calls[1][1]["target"] == "unbound_forward"


def test_the_list_of_held_forwards_is_read_under_check_mode_so_a_stale_forward_shows_as_a_change():
    tasks = yaml.safe_load((REPO / "ansible/roles/opnsense_gateway/tasks/forwards.yaml").read_text())
    listing = next(task for task in tasks if "oxlorg.opnsense.list" in task)

    assert listing["check_mode"] is False


def test_the_forwards_are_applied_after_the_dhcp_scopes():
    tasks = yaml.safe_load((REPO / "ansible/roles/opnsense_gateway/tasks/main.yaml").read_text())
    block = next(task for task in tasks if "module_defaults" in task)
    includes = [task["ansible.builtin.include_tasks"] for task in block["block"]]

    assert includes == ["policy.yaml", "dhcp.yaml", "forwards.yaml"]


def test_a_forward_the_gateway_holds_is_judged_by_the_domain_and_server_fields_of_the_apis_own_record():
    import jinja2

    tasks = yaml.safe_load((REPO / "ansible/roles/opnsense_gateway/tasks/forwards.yaml").read_text())
    removal = next(task for task in tasks if task.get("name") == "Remove a forward the play does not write")
    held = {"uuid": "u1", "domain": "internal.kit.lab", "server": "192.0.2.99", "port": "53", "enabled": "1", "forward_tcp_upstream": "0", "description": ""}
    wanted = ["internal.kit.lab|192.168.20.3", "internal.kit.lab|192.168.20.6"]
    env = jinja2.Environment(autoescape=False)  # noqa: S701 - an Ansible conditional, not HTML

    def removes(record):
        return env.from_string("{{ " + removal["when"] + " }}").render(opnsense_gateway_held=record, opnsense_gateway_wanted=wanted) == "True"

    assert removes(held)
    assert not removes({**held, "server": "192.168.20.3"})
    assert removal["oxlorg.opnsense.unbound_forward"]["target"] == "{{ opnsense_gateway_held.server }}"


# The rules the gateway holds are the play's own: the removal's wanted set is derived from what the tasks write.

POLICY = REPO / "ansible/roles/opnsense_gateway/tasks/policy.yaml"


def _policy_tasks() -> list[dict]:
    return yaml.safe_load(POLICY.read_text())


def _rule_env():
    import itertools
    import json

    import jinja2

    env = jinja2.Environment(autoescape=False)  # noqa: S701 - Ansible expressions, not HTML
    env.filters["product"] = lambda first, second: list(itertools.product(first, second))
    env.filters["bool"] = lambda value: str(value).lower() in {"true", "1", "yes"}
    env.filters["to_json"] = json.dumps
    return env


def _expression(env, source, scope):
    return env.compile_expression(source.removeprefix("{{").removesuffix("}}").strip())(**scope)


def _scope(defaults: dict, *, cd_agent: bool, scratch_wan: bool = True) -> dict:
    """The role's defaults with the facts its tasks set, which the rule tasks and the removal read."""
    scope = {**defaults, "opnsense_gateway_cd_agent_management": cd_agent, "opnsense_gateway_scratch_wan": scratch_wan}
    for task in _policy_tasks():
        for name, source in task.get("ansible.builtin.set_fact", {}).items():
            scope[name] = _expression(_rule_env(), source, scope)
    return scope


def _written_descriptions(defaults: dict, *, cd_agent: bool, scratch_wan: bool = True) -> list[str]:
    """What the rule tasks write, by rendering each task's description over its own loop."""
    env = _rule_env()
    scope = _scope(defaults, cd_agent=cd_agent, scratch_wan=scratch_wan)
    written = []
    for task in _policy_tasks():
        if "oxlorg.opnsense.rule" not in task or task["oxlorg.opnsense.rule"].get("state") == "absent":
            continue
        rule = task["oxlorg.opnsense.rule"]
        control = task.get("loop_control", {})
        items = _expression(env, task["loop"], scope) if "loop" in task else [None]
        for index, item in enumerate(items):
            local = {**scope, control.get("loop_var", "item"): item, control.get("index_var", "_index"): index}
            state = _expression(env, rule["state"], local) if "state" in rule else "present"
            if state == "present":
                written.append(_expression(env, rule["description"], local))
    return written


def _wanted(defaults: dict, *, cd_agent: bool, scratch_wan: bool = True) -> list[str]:
    import json

    removal = _policy_tasks()[-1]
    scope = _scope(defaults, cd_agent=cd_agent, scratch_wan=scratch_wan)
    return json.loads(_rule_env().from_string(removal["vars"]["opnsense_gateway_wanted_rules"]).render(**scope))


@pytest.mark.parametrize("scratch_wan", [False, True])
@pytest.mark.parametrize("cd_agent", [False, True])
def test_the_rules_the_removal_keeps_are_exactly_the_rules_the_tasks_write(defaults, cd_agent, scratch_wan):
    assert sorted(_wanted(defaults, cd_agent=cd_agent, scratch_wan=scratch_wan)) == sorted(
        _written_descriptions(defaults, cd_agent=cd_agent, scratch_wan=scratch_wan)
    )


def test_every_rule_the_play_writes_has_a_distinct_description_because_the_play_matches_by_it(defaults):
    written = _written_descriptions(defaults, cd_agent=True)

    assert len(set(written)) == len(written)
    assert all(written)


def test_the_guard_rule_and_the_flows_switched_off_are_among_the_rules_the_removal_keeps(defaults):
    wanted = _wanted(defaults, cd_agent=False)
    switched_off = [flow["name"] for flow in defaults["opnsense_gateway_flows"] if flow.get("enabled") is False]

    assert defaults["opnsense_gateway_rule_names"]["guard"] in wanted
    assert switched_off
    assert set(switched_off) <= set(wanted)


def test_a_rule_switched_off_by_its_switch_is_not_kept_so_the_removal_agrees_with_the_task_that_removes_it(defaults):
    cd_rule = defaults["opnsense_gateway_rule_names"]["cd_agent"] % defaults["opnsense_gateway_cd_agent_zone"]

    assert cd_rule not in _wanted(defaults, cd_agent=False)
    assert cd_rule in _wanted(defaults, cd_agent=True)


def test_every_zone_says_whether_it_may_ask_the_gateway_for_dns(defaults):
    assert all(isinstance(zone["gateway_dns"], bool) for zone in defaults["opnsense_gateway_zones"])


def test_a_zone_that_may_not_ask_the_gateway_for_dns_is_written_its_other_services_and_no_dns_rule(defaults):
    zones = [{**zone, "gateway_dns": zone["name"] != "services"} for zone in defaults["opnsense_gateway_zones"]]
    changed = {**defaults, "opnsense_gateway_zones": zones}
    pattern = defaults["opnsense_gateway_rule_names"]["zone_service"]
    written = _written_descriptions(changed, cd_agent=False)

    assert pattern % ("services", "DNS over TCP") not in written
    assert pattern % ("services", "DNS over UDP") not in written
    assert pattern % ("services", "NTP") in written
    assert pattern % ("services", "ping") in written
    assert pattern % ("desktops", "DNS over UDP") in written
    assert sorted(_wanted(changed, cd_agent=False)) == sorted(written)


def test_a_zone_that_may_not_ask_the_gateway_for_dns_has_its_dns_rule_removed_because_the_removal_does_not_keep_it(defaults):
    zones = [{**zone, "gateway_dns": zone["name"] != "services"} for zone in defaults["opnsense_gateway_zones"]]
    changed = {**defaults, "opnsense_gateway_zones": zones}
    pattern = defaults["opnsense_gateway_rule_names"]["zone_service"]

    assert pattern % ("services", "DNS over UDP") in _wanted(defaults, cd_agent=False)
    assert pattern % ("services", "DNS over UDP") not in _wanted(changed, cd_agent=False)


def test_the_zone_without_internet_has_no_internet_rules_kept(defaults):
    names = defaults["opnsense_gateway_rule_names"]
    isolated = next(zone["name"] for zone in defaults["opnsense_gateway_zones"] if not zone["internet"])
    wanted = _wanted(defaults, cd_agent=False)

    assert names["internet"] % isolated not in wanted
    assert names["direct_dns"] % isolated not in wanted


def test_the_rules_are_read_after_every_rule_is_written_and_removed_by_description(defaults):
    tasks = _policy_tasks()
    modules = [next(key for key in task if key.startswith(("oxlorg.opnsense.", "ansible.builtin."))) for task in tasks]
    removal = tasks[-1]["oxlorg.opnsense.rule"]
    listing = next(task for task in tasks if "oxlorg.opnsense.list" in task)

    assert modules[-3:] == ["oxlorg.opnsense.list", "ansible.builtin.assert", "oxlorg.opnsense.rule"]
    assert "oxlorg.opnsense.rule" in modules[:-3]
    assert listing["oxlorg.opnsense.list"]["target"] == "rule"
    assert listing["check_mode"] is False
    assert removal["state"] == "absent"
    assert removal["match_fields"] == ["description"]


def test_a_held_rule_is_removed_unless_its_whole_description_is_one_the_play_writes(defaults):
    import json

    removal = _policy_tasks()[-1]
    env = _rule_env()
    wanted = json.dumps(_wanted(defaults, cd_agent=False))
    env.filters["from_json"] = json.loads
    guard = defaults["opnsense_gateway_rule_names"]["guard"]

    def removes(description):
        scope = {"opnsense_gateway_held": {"description": description}, "opnsense_gateway_wanted_rules": wanted}
        return env.from_string("{{ " + removal["when"] + " }}").render(**scope) == "True"

    assert removes("a rule the play does not write")
    assert removes("services: Intern")  # a part of a description the play writes
    assert not removes(guard)
    assert not removes("services: Internet")


# The coding-agent zone (ADR 0053): its host is reached on SSH from two sources and the zone reaches nothing of the gateway's but time and echo.


def _flow(defaults: dict, name: str) -> dict:
    return next(flow for flow in defaults["opnsense_gateway_flows"] if flow["name"] == name)


def test_the_coding_zone_is_vlan_30_with_no_internet_no_dhcp_and_no_dns_from_the_gateway(defaults):
    zone = next(zone for zone in defaults["opnsense_gateway_zones"] if zone["name"] == "coding")

    assert (zone["vlan"], zone["interface"]) == (30, "opt4")
    assert (zone["internet"], zone["dhcp"], zone["gateway_dns"]) == (False, False, False)


def test_the_coding_zone_is_the_only_zone_the_gateway_does_not_answer_dns_for(defaults):
    refused = [zone["name"] for zone in defaults["opnsense_gateway_zones"] if not zone["gateway_dns"]]

    assert refused == ["coding"]


def test_the_coding_zone_is_written_time_and_echo_to_the_gateway_and_no_dns(defaults):
    pattern = defaults["opnsense_gateway_rule_names"]["zone_service"]
    written = _written_descriptions(defaults, cd_agent=False)

    assert [name for name in written if name.startswith("coding: ")] == [pattern % ("coding", "NTP"), pattern % ("coding", "ping")]


def test_the_coding_zone_is_written_no_direct_dns_or_internet_rule_so_its_only_way_out_is_the_proxy_a_later_project_adds(defaults):
    names = defaults["opnsense_gateway_rule_names"]
    wanted = _wanted(defaults, cd_agent=True)

    assert names["internet"] % "coding" not in wanted
    assert names["direct_dns"] % "coding" not in wanted


def test_the_coding_agent_host_has_the_address_the_vmid_scheme_gives_vmid_302(defaults):
    vmid = 302
    address = f"192.168.{vmid // 50 * 5}.{vmid % 50}"

    assert defaults["opnsense_gateway_hosts"]["host_coding_agent"] == address == "192.168.30.2"
    assert ipaddress.ip_address(address) in zone_network(defaults, "net_coding")


def test_the_coding_agent_host_is_reached_on_ssh_from_the_operator_hosts_and_the_tailscale_router_and_from_nothing_else(defaults):
    reaching = [flow for flow in defaults["opnsense_gateway_flows"] if flow["destination"] == "host_coding_agent"]

    assert {(flow["source"], tuple(flow["zones"])) for flow in reaching} == {("operator_hosts", ("desktops", "management")), ("host_tailscale", ("services",))}
    assert all((flow["protocol"], flow["port"]) == ("TCP", "22") and flow.get("enabled", True) for flow in reaching)


def test_no_flow_starts_in_the_coding_zone_so_it_reaches_no_other_zone(defaults):
    assert [flow["name"] for flow in defaults["opnsense_gateway_flows"] if "coding" in flow["zones"]] == []


def test_no_flow_reaches_into_the_coding_zone_but_the_two_that_name_its_host(defaults):
    into = [flow["name"] for flow in defaults["opnsense_gateway_flows"] if flow["destination"] in {"net_coding", "host_coding_agent"}]

    assert into == ["operator hosts to the coding-agent host over SSH", "tailscale router to the coding-agent host over SSH"]
    assert _flow(defaults, into[0])["source"] == "operator_hosts"


def test_the_flows_the_coding_zone_adds_come_before_the_scratch_zones_so_no_rule_already_on_the_gateway_changes_its_sequence(defaults):
    assert [flow["name"] for flow in defaults["opnsense_gateway_flows"]][-3:-1] == [
        "operator hosts to the coding-agent host over SSH",
        "tailscale router to the coding-agent host over SSH",
    ]


# The zone that serves a scratch gateway its WAN (ADR 0120).


def test_the_scratch_zone_is_vlan_10_on_the_seeds_first_interface_with_internet_and_a_scope(defaults):
    zone = next(zone for zone in defaults["opnsense_gateway_zones"] if zone["name"] == "scratch")

    assert (zone["vlan"], zone["interface"]) == (patch_config.WAN_ZONE_VLAN, "opt1")
    assert (zone["internet"], zone["dhcp"], zone["gateway_dns"]) == (True, True, True)
    assert zone["scratch_wan"] is True


def test_only_the_scratch_zone_and_its_flow_are_marked_as_switchable(defaults):
    assert [zone["name"] for zone in defaults["opnsense_gateway_zones"] if "scratch_wan" in zone] == ["scratch"]
    assert [flow["name"] for flow in defaults["opnsense_gateway_flows"] if "scratch_wan" in flow] == ["scratch gateway to the Proxmox node"]
    assert defaults["opnsense_gateway_scratch_wan"] is True


def test_the_scratch_gateways_address_is_reserved_in_its_zone_below_the_pool_and_has_the_mac_of_vmid_501s_wan_nic(defaults):
    gateway = defaults["opnsense_gateway_scratch_gateway"]
    last = int(gateway["address"].split(".")[-1])

    assert gateway["zone"] == "scratch"
    assert ipaddress.ip_address(gateway["address"]) in ipaddress.ip_network("192.168.10.0/24")
    assert 2 <= last < defaults["opnsense_gateway_dhcp_pool"]["first"]
    assert defaults["opnsense_gateway_hosts"]["host_scratch_gateway"] == gateway["address"]
    vmid = 501
    assert gateway["mac"] == f"bc:24:11:{vmid // 256:02x}:{vmid % 256:02x}:00"


def test_the_only_flow_from_the_scratch_zone_is_its_gateway_to_the_nodes_ssh_and_api_ports(defaults):
    flows = [flow for flow in defaults["opnsense_gateway_flows"] if "scratch" in flow["zones"]]

    assert len(flows) == 1
    assert (flows[0]["zones"], flows[0]["source"], flows[0]["destination"], flows[0]["port"]) == (
        ["scratch"],
        "host_scratch_gateway",
        "host_proxmox_node",
        "proxmox_node_ports",
    )
    assert not [flow for flow in defaults["opnsense_gateway_flows"] if flow["destination"] == "net_scratch"]


def test_the_scratch_zone_and_everything_written_for_it_go_when_the_switch_is_off(defaults):
    on, off = _scope(defaults, cd_agent=False), _scope(defaults, cd_agent=False, scratch_wan=False)

    assert [zone["name"] for zone in on["opnsense_gateway_live_zones"]][-1] == "scratch"
    assert "scratch" not in [zone["name"] for zone in off["opnsense_gateway_live_zones"]]
    assert [zone["name"] for zone in off["opnsense_gateway_live_zones"]] == [
        zone["name"] for zone in defaults["opnsense_gateway_zones"] if "scratch_wan" not in zone
    ]
    assert off["opnsense_gateway_live_flows"] == [flow for flow in defaults["opnsense_gateway_flows"] if "scratch_wan" not in flow]
    assert {"scratch gateway to the Proxmox node", "scratch: Internet"} <= set(_wanted(defaults, cd_agent=False))
    assert not [name for name in _wanted(defaults, cd_agent=False, scratch_wan=False) if "scratch" in name]


def test_the_scratch_gateways_reservation_is_kept_only_while_the_zone_is_written():
    tasks = yaml.safe_load((REPO / "ansible/roles/opnsense_gateway/tasks/dhcp.yaml").read_text())
    gather = next(task for task in tasks if "ansible.builtin.set_fact" in task)
    expression = gather["ansible.builtin.set_fact"]["opnsense_gateway_reservations"]
    defaults = yaml.safe_load((REPO / "ansible/roles/opnsense_gateway/defaults/main.yaml").read_text())
    mine = [{"name": "operator", "zone": "desktops", "address": "192.168.40.250", "mac": "bc:24:11:00:01:91"}]

    for switch in (True, False):
        scope = {**defaults, "opnsense_gateway_dhcp_reservations": mine, "opnsense_gateway_scratch_wan": switch}
        kept = _expression(_rule_env(), expression, scope)
        assert kept == mine + ([defaults["opnsense_gateway_scratch_gateway"]] if switch else [])
