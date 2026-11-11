"""Tests for network_checks.rules: one case per rule of ADR 0094, then the committed flow list.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import pytest
from network_checks import rules
from network_checks.flow_list import FLOWS_PATH, load_flow_list


def violations(write_flows, data):
    return rules.check(load_flow_list(write_flows(data)))


def broken(write_flows, data) -> set[tuple[str, str]]:
    return {(violation.name, violation.rule) for violation in violations(write_flows, data)}


def test_a_good_list_breaks_no_rule(write_flows, good):
    assert violations(write_flows, good) == []


def test_a_repeated_flow_id_is_reported(write_flows, good):
    good["flows"][1]["id"] = "alpha-dns"

    assert ("alpha-dns", "unique-ids") in broken(write_flows, good)


def test_a_flow_from_an_undeclared_zone_is_reported(write_flows, good):
    good["flows"][1]["from"] = "gamma"

    assert ("beta-web", "known-zone") in broken(write_flows, good)


def test_a_zone_with_no_allow_flow_is_reported(write_flows, good):
    good["zones"]["gamma"] = {"subnet": "10.3.0.0/24", "canary": "10.3.0.250"}

    assert ("gamma", "zone-allow") in broken(write_flows, good)


def test_a_control_that_is_not_an_allow_flow_is_reported(write_flows, good):
    good["flows"][2]["control"] = "no-such-flow"

    assert ("alpha-ssh-blocked", "control-is-allow") in broken(write_flows, good)


def test_a_control_naming_a_deny_is_reported(write_flows, good):
    good["flows"].append(
        {"id": "second-block", "from": "beta", "to": {"address": "10.2.0.1", "port": 22}, "kind": "connect", "expect": "deny", "control": "alpha-ssh-blocked"}
    )

    assert ("second-block", "control-is-allow") in broken(write_flows, good)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"address": "10.2.0.9", "port": 22}, id="other-address"),
        pytest.param({"address": "10.2.0.1", "port": 2222}, id="other-port"),
        pytest.param({"address": "10.2.0.1", "port": 22, "protocol": "tcp", "kind": "ntp"}, id="other-kind"),
    ],
)
def test_a_control_trying_something_else_is_reported(write_flows, good, change):
    flow = good["flows"][2]
    flow["to"] = {"address": change["address"], "port": change["port"]}
    if "kind" in change:
        flow["kind"] = change["kind"]
        flow["to"]["protocol"] = "udp"

    assert ("alpha-ssh-blocked", "control-same-target") in broken(write_flows, good)


def test_a_pair_of_zones_with_no_flow_is_reported(write_flows, good):
    good["flows"] = [flow for flow in good["flows"] if flow["id"] != "beta-web"]

    reported = broken(write_flows, good)

    assert ("beta -> alpha", "pair-covered") in reported
    assert ("alpha -> beta", "pair-covered") not in reported


def test_a_flow_to_a_name_does_not_cover_a_pair(write_flows, good):
    good["flows"][1]["to"] = {"address": "gateway.lab", "port": 443}

    assert ("beta -> alpha", "pair-covered") in broken(write_flows, good)


def test_the_committed_flow_list_breaks_no_rule():
    assert rules.check(load_flow_list(FLOWS_PATH)) == []


def test_main_exits_zero_for_a_good_list_and_prints_its_size(write_flows, good, monkeypatch, capsys):
    monkeypatch.setattr(rules, "FLOWS_PATH", write_flows(good))

    assert rules.main() == 0
    assert "2 zones, 4 flows" in capsys.readouterr().out


def test_main_exits_one_and_names_the_rule_for_a_violation(write_flows, good, monkeypatch, capsys):
    good["flows"][1]["id"] = "alpha-dns"
    monkeypatch.setattr(rules, "FLOWS_PATH", write_flows(good))

    assert rules.main() == 1
    assert "alpha-dns: [unique-ids]" in capsys.readouterr().err


def test_main_exits_one_for_a_list_the_loader_refuses(write_flows, monkeypatch, capsys):
    monkeypatch.setattr(rules, "FLOWS_PATH", write_flows("- not a mapping\n"))

    assert rules.main() == 1
    assert "must be a mapping" in capsys.readouterr().err
