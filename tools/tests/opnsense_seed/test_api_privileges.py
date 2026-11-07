"""The API paths the repo calls must be matched by the privileges the seed gives the API user.

acl_patterns.json holds the URL patterns of those privileges as the gateway's own tables (ACL.xml of
26.1.11) list them. A pattern matches the whole path, case-insensitively, and only `*` is a wildcard, so a
path spelled differently from a literal pattern (systemInformation for system_information) is refused.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tofu/modules/proxmox_opnsense_vm/seed"))

import patch_config  # noqa: E402 - the seed builder, imported by path

PATTERNS = json.loads((Path(__file__).with_name("acl_patterns.json")).read_text())
FILES = [REPO / "ansible/roles/opnsense_gateway/tasks/main.yaml", REPO / "tofu/scratch/opnsense/update_gateway.sh"]
ROLE_TASKS = REPO / "ansible/roles/opnsense_gateway/tasks"
# What each oxlorg.opnsense module the role calls asks the API for, read from the collection at the commit the role pins:
# api/<API_MOD>/<API_CONT>/<command> for its settings, and its reload at api/<API_MOD>/<API_CONT_REL, else API_CONT>/<API_CMD_REL,
# else reconfigure>. The modules build these paths in code, so no file of the repo spells them.
MODULE_PATHS = {
    "alias": ["api/firewall/alias/get", "api/firewall/alias/reconfigure"],
    "rule": ["api/firewall/filter/get", "api/firewall/filter/apply"],
    "unbound_forward": ["api/unbound/settings/get", "api/unbound/service/reconfigure"],
    "dhcp_general": ["api/kea/dhcpv4/get", "api/kea/service/reconfigure"],
    "dhcp_subnet": ["api/kea/dhcpv4/get", "api/kea/service/reconfigure"],
    "dhcp_reservation": ["api/kea/dhcpv4/get", "api/kea/service/reconfigure"],
    "dnsmasq_general": ["api/dnsmasq/settings/get", "api/dnsmasq/service/reconfigure"],
}
MODULE = re.compile(r"^\s+oxlorg\.opnsense\.(\w+):", re.MULTILINE)
# `list` reads whatever its target module manages, so the target is the module whose paths count.
LIST_TARGET = re.compile(r"^\s+oxlorg\.opnsense\.list:\s*\n\s+target: (\w+)", re.MULTILINE)
# Paths a script builds from a function argument: `get core/firmware/upgradestatus`.
CALL = re.compile(r"(?:\bget|\bpost) ((?:core|diagnostics|firewall|kea|dnsmasq)/[\w/]+)")
LITERAL = re.compile(r"/api/([\w/]+)")


def allowed(path: str) -> bool:
    patterns = [p for name in patch_config.API_PRIVILEGES for p in PATTERNS[name]]
    return any(fnmatch.fnmatchcase(path.lower(), p.lower()) for p in patterns)


def called_paths() -> list[tuple[Path, str]]:
    found = []
    for file in FILES:
        text = file.read_text()
        found += [(file, f"api/{m}") for m in LITERAL.findall(text)]
        found += [(file, f"api/{m}") for m in CALL.findall(text)]
    return found


def modules_called(text: str) -> set[str]:
    return (set(MODULE.findall(text)) - {"list"}) | set(LIST_TARGET.findall(text))


def role_modules() -> set[str]:
    return {module for file in sorted(ROLE_TASKS.glob("*.yaml")) for module in modules_called(file.read_text())}


def test_the_patterns_are_those_of_the_privileges_the_seed_gives():
    assert set(PATTERNS) == set(patch_config.API_PRIVILEGES)


def test_the_repo_calls_some_paths_so_the_check_below_checks_something():
    assert len(called_paths()) >= 6


@pytest.mark.parametrize(("file", "path"), sorted(set(called_paths()), key=str))
def test_every_api_path_the_repo_calls_is_matched_by_a_privilege_of_the_api_user(file, path):
    assert allowed(path), f"{file.name} calls {path}, which no privilege of the API user matches"


@pytest.mark.parametrize(
    "path", ["api/unbound/settings/get", "api/unbound/settings/addForward", "api/unbound/settings/delForward", "api/unbound/service/reconfigure"]
)
def test_the_unbound_calls_of_the_collection_are_matched(path):
    assert allowed(path)


def test_a_path_spelled_with_camel_case_where_the_pattern_is_snake_case_is_refused():
    assert allowed("api/diagnostics/system/system_information")
    assert not allowed("api/diagnostics/system/systemInformation")


def test_the_role_calls_the_collection_modules_whose_paths_are_listed_here_and_no_others():
    assert role_modules() == set(MODULE_PATHS)


@pytest.mark.parametrize(
    ("module", "path"),
    [(module, path) for module, paths in sorted(MODULE_PATHS.items()) for path in paths],
    ids=lambda value: str(value),
)
def test_every_api_path_a_collection_module_of_the_role_asks_for_is_matched_by_a_privilege_of_the_api_user(module, path):
    assert allowed(path), f"the {module} module asks for {path}, which no privilege of the API user matches"


def test_a_module_the_role_starts_calling_is_found_even_when_it_is_asked_through_list():
    text = "- name: a\n  oxlorg.opnsense.interface_vlan:\n    device: vtnet1\n- name: b\n  oxlorg.opnsense.list:\n    target: source_nat\n"
    assert modules_called(text) == {"interface_vlan", "source_nat"}
    assert not set(MODULE_PATHS) >= modules_called(text)


def test_the_module_defaults_group_and_prose_naming_the_collection_are_not_taken_for_a_module_call():
    text = "  module_defaults:\n    group/oxlorg.opnsense.all:\n      api_key: x\n- name: List the installed oxlorg.opnsense collection\n"
    assert modules_called(text) == set()


@pytest.mark.parametrize("path", ["api/firewall/source_nat/get", "api/interfaces/vlan_settings/get", "api/auth/user/search"])
def test_a_path_of_a_privilege_the_api_user_does_not_hold_is_refused(path):
    assert not allowed(path)
