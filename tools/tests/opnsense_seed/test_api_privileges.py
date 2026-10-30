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
