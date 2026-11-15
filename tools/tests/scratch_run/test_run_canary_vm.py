from __future__ import annotations

import re
from pathlib import Path

import pytest
from network_checks.flow_list import load_flow_list
from network_checks.scratch_plan import zone_vlans
from scratch_run.canary_vm import ADMIN_USER, DNS_DOMAIN, public_key_of, tfvars, vm_id

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItestkey runner@scratch"


@pytest.mark.parametrize(
    ("zone", "expected"),
    [
        pytest.param("services", 208, id="services"),
        pytest.param("others", 308, id="others"),
        pytest.param("desktops", 408, id="desktops"),
        pytest.param("isolated", 508, id="isolated"),
        pytest.param("experimental", 608, id="experimental"),
    ],
)
def test_the_vmid_of_a_zones_canary_is_the_one_whose_scheme_address_is_its_canary(zone, expected):
    assert vm_id(zone, load_flow_list(), zone_vlans()) == expected


def test_a_vmid_agrees_with_the_modules_own_scheme_for_every_zone(subtests):
    flow_list, vlans = load_flow_list(), zone_vlans()
    for name, zone in flow_list.zones.items():
        with subtests.test(zone=name):
            found = vm_id(name, flow_list, vlans)
            assert (found // 100 * 10, f"192.168.{found // 100 * 10}.{found % 100}") == (vlans[name], str(zone.canary))


@pytest.mark.parametrize(
    ("zone", "vlans", "message"),
    [
        pytest.param("nowhere", {"services": 20}, "the zone `nowhere` is not in the flow list", id="not-in-the-flow-list"),
        pytest.param("services", {}, "the gateway's play has no zone `services`", id="not-in-the-play"),
        pytest.param("services", {"services": 25}, "not an address a VMID of the lab's scheme gives on VLAN 25", id="vlan-not-a-multiple-of-ten"),
        pytest.param("services", {"services": 30}, "not an address a VMID of the lab's scheme gives on VLAN 30", id="canary-not-on-that-vlan"),
    ],
)
def test_a_zone_that_has_no_vmid_is_refused_with_the_reason(zone, vlans, message):
    with pytest.raises(ValueError, match=message):
        vm_id(zone, load_flow_list(), vlans)


def test_the_variables_are_the_scratch_roots_and_carry_the_key_and_the_bridge():
    assert tfvars(208, "services", "vmbr9", KEY + "\n", "pve") == {
        "vm_id": 208,
        "name": "canary-services",
        "lan_bridge": "vmbr9",
        "node_name": "pve",
        "admin_username": ADMIN_USER,
        "ssh_public_keys": [KEY],
        "dns_domain": DNS_DOMAIN,
    }


def test_a_template_vmid_is_passed_on_as_a_number_when_one_is_given():
    assert tfvars(208, "services", "vmbr9", KEY, "pve", "106")["template_vm_id"] == 106


def test_the_variables_are_names_the_scratch_root_declares():
    text = (Path(__file__).resolve().parents[3] / "tofu/scratch/ubuntu/variables.tf").read_text()
    declared = set(re.findall(r'^variable "(\w+)"', text, flags=re.MULTILINE))
    assert set(tfvars(208, "services", "vmbr9", KEY, "pve", "106")) <= declared


def test_the_public_key_is_the_one_line_of_its_file(tmp_path):
    path = tmp_path / "k.pub"
    path.write_text(KEY + "\n")
    assert public_key_of(path) == KEY


@pytest.mark.parametrize("text", ["", "not a key\n", f"{KEY}\n{KEY}\n"])
def test_a_file_that_is_not_exactly_one_public_key_is_refused(tmp_path, text):
    path = tmp_path / "k.pub"
    path.write_text(text)
    with pytest.raises(ValueError, match="exactly one ssh public key"):
        public_key_of(path)
