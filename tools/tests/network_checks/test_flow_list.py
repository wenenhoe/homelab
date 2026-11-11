"""Tests for network_checks.flow_list: what the loader refuses, then what it returns.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import ipaddress

import pytest
from network_checks.flow_list import FLOWS_PATH, Destination, FlowListError, load_flow_list


def refused(write_flows, data) -> list[str]:
    with pytest.raises(FlowListError) as exc:
        load_flow_list(write_flows(data))
    return exc.value.problems


def test_a_good_list_loads_with_its_zones_and_flows(write_flows, good):
    flow_list = load_flow_list(write_flows(good))

    assert list(flow_list.zones) == ["alpha", "beta"]
    assert flow_list.zones["alpha"].subnet == ipaddress.IPv4Network("10.1.0.0/24")
    assert flow_list.zones["alpha"].canary == ipaddress.IPv4Address("10.1.0.250")
    assert [flow.id for flow in flow_list.flows] == ["alpha-dns", "beta-web", "alpha-ssh-blocked", "alpha-ssh"]


def test_the_protocol_defaults_to_the_kinds_own(write_flows, good):
    good["flows"].append({"id": "time", "from": "alpha", "to": {"address": "10.2.0.1", "port": 123}, "kind": "ntp", "expect": "allow"})
    flow_list = load_flow_list(write_flows(good))

    by_id = {flow.id: flow for flow in flow_list.flows}
    assert by_id["beta-web"].destination == Destination("10.1.0.1", 443, "tcp")
    assert by_id["time"].destination == Destination("10.2.0.1", 123, "udp")


def test_a_ping_has_no_port_or_protocol(write_flows, good):
    good["flows"].append({"id": "echo", "from": "alpha", "to": {"address": "10.2.0.1"}, "kind": "ping", "expect": "allow"})
    flow_list = load_flow_list(write_flows(good))

    assert {flow.id: flow for flow in flow_list.flows}["echo"].destination == Destination("10.2.0.1", None, None)


def test_a_destination_may_be_a_name(write_flows, good):
    good["flows"][1]["to"]["address"] = "github.com"
    flow_list = load_flow_list(write_flows(good))

    destination = flow_list.flows[1].destination
    assert (destination.address, destination.ip()) == ("github.com", None)


def test_the_committed_flow_list_loads():
    load_flow_list(FLOWS_PATH)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(lambda d: d.update(extra=1), "unknown key `extra`", id="top-level-unknown-key"),
        pytest.param(lambda d: d.update(zones=[]), "`zones` must be a mapping", id="zones-not-a-mapping"),
        pytest.param(lambda d: d.update(flows={}), "`flows` must be a list", id="flows-not-a-list"),
        pytest.param(lambda d: d["zones"]["alpha"].update(extra=1), "zone `alpha` has the unknown key `extra`", id="zone-unknown-key"),
        pytest.param(lambda d: d["zones"]["alpha"].update(subnet="10.1.0.0/33"), "zone `alpha` needs a `subnet`", id="subnet-invalid"),
        pytest.param(lambda d: d["zones"]["alpha"].pop("canary"), "zone `alpha` needs a `canary`", id="canary-missing"),
        pytest.param(lambda d: d["zones"]["alpha"].update(canary="10.9.0.1"), "not inside 10.1.0.0/24", id="canary-outside-subnet"),
        pytest.param(lambda d: d["zones"].update({"Bad_Name": {"subnet": "10.3.0.0/24", "canary": "10.3.0.1"}}), "lower-case letters", id="zone-name-shape"),
        pytest.param(lambda d: d["flows"][0].update(extra=1), "flow `alpha-dns` has the unknown key `extra`", id="flow-unknown-key"),
        pytest.param(lambda d: d["flows"][0].update(id="Bad Id"), "needs an `id`", id="flow-id-shape"),
        pytest.param(lambda d: d["flows"][0].pop("from"), "needs `from`", id="from-missing"),
        pytest.param(lambda d: d["flows"][0].update(kind="telnet"), "needs `kind` to be one of", id="kind-unknown"),
        pytest.param(lambda d: d["flows"][0].update(expect="maybe"), "needs `expect` to be allow or deny", id="expect-unknown"),
        pytest.param(lambda d: d["flows"][0].update(to="10.2.0.1"), "needs `to` as a mapping", id="to-not-a-mapping"),
        pytest.param(lambda d: d["flows"][0]["to"].update(extra=1), "`to` has the unknown key `extra`", id="to-unknown-key"),
        pytest.param(lambda d: d["flows"][0]["to"].pop("address"), "needs `to.address`", id="address-missing"),
        pytest.param(lambda d: d["flows"][0]["to"].update(address="999.1.1.1"), "neither an IPv4 address nor a host name", id="address-invalid"),
        pytest.param(lambda d: d["flows"][1]["to"].pop("port"), "needs `to.port`", id="port-missing"),
        pytest.param(lambda d: d["flows"][1]["to"].update(port=70000), "needs `to.port`", id="port-out-of-range"),
        pytest.param(lambda d: d["flows"][1]["to"].update(protocol="udp"), "`to.protocol` must be one of tcp", id="connect-over-udp"),
        pytest.param(lambda d: d["flows"][0]["to"].pop("protocol"), "`to.protocol` must be one of udp, tcp", id="dns-protocol-missing"),
        pytest.param(lambda d: d["flows"][1].update(kind="ping"), "ping, which takes no port or protocol", id="ping-with-a-port"),
        pytest.param(lambda d: d["flows"][2].pop("control"), "is a deny and needs a `control`", id="deny-without-control"),
        pytest.param(lambda d: d["flows"][1].update(control="alpha-ssh"), "an allow and takes no `control`", id="allow-with-control"),
        pytest.param(lambda d: d["flows"][0].pop("query"), "needs a `query`", id="dns-without-query"),
        pytest.param(lambda d: d["flows"][1].update(query="host.lab"), "takes a `query` only when it is a dns flow", id="query-on-connect"),
        pytest.param(lambda d: d["flows"][0].update(tags="smoke"), "`tags` to be a list", id="tags-not-a-list"),
    ],
)
def test_a_shape_problem_is_refused_with_its_message(write_flows, good, change, message):
    change(good)

    assert any(message in problem for problem in refused(write_flows, good))


def test_every_problem_is_named_not_just_the_first(write_flows, good):
    good["flows"][0]["kind"] = "telnet"
    good["flows"][1]["expect"] = "maybe"

    problems = refused(write_flows, good)

    assert len(problems) >= 2


def test_a_repeated_zone_name_is_refused(write_flows):
    text = "zones:\n  alpha: {subnet: 10.1.0.0/24, canary: 10.1.0.1}\n  alpha: {subnet: 10.2.0.0/24, canary: 10.2.0.1}\nflows: []\n"

    assert any("duplicate key 'alpha'" in problem for problem in refused(write_flows, text))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        pytest.param("- a\n- b\n", "must be a mapping", id="not-a-mapping"),
        pytest.param("zones: [unclosed\n", "isn't valid YAML", id="invalid-yaml"),
    ],
)
def test_a_file_that_is_not_a_flow_list_is_refused(write_flows, text, message):
    assert any(message in problem for problem in refused(write_flows, text))


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(FlowListError, match="can't read"):
        load_flow_list(tmp_path / "absent.yaml")
