"""The gateway role's zone list and the seed that creates the zones' interfaces must agree."""

from __future__ import annotations

import sys
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
