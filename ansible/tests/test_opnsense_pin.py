"""The OPNsense collection commit is written in two files, and they must name the same one; Renovate leaves it alone."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml
from ci import json5

ANSIBLE_DIR = Path(__file__).resolve().parents[1]
RENOVATE_CONFIG = ANSIBLE_DIR.parent / ".github/renovate.json5"
COLLECTION_URL = "https://github.com/O-X-L/ansible-opnsense.git"


@pytest.fixture
def role_defaults() -> dict:
    return yaml.safe_load((ANSIBLE_DIR / "roles/opnsense_gateway/defaults/main.yaml").read_text())


@pytest.fixture
def collection_entry() -> dict:
    entries = yaml.safe_load((ANSIBLE_DIR / "requirements.yml").read_text())["collections"]
    return next(entry for entry in entries if entry["name"] == COLLECTION_URL)


def test_requirements_install_the_collection_at_the_commit_the_role_is_pinned_to(role_defaults, collection_entry):
    assert collection_entry["version"] == role_defaults["opnsense_gateway_collection_commit"]


def test_the_collection_is_installed_from_git_because_the_pin_is_a_commit(collection_entry):
    assert collection_entry["type"] == "git"


def test_the_pin_is_a_full_commit_hash_not_a_branch_or_tag(role_defaults):
    assert re.fullmatch(r"[0-9a-f]{40}", role_defaults["opnsense_gateway_collection_commit"])


def test_the_release_is_a_three_part_version(role_defaults):
    assert re.fullmatch(r"\d+\.\d+\.\d+", role_defaults["opnsense_gateway_release"])


def test_renovate_does_not_look_up_the_collection_pinned_to_a_commit():
    url = urlparse(COLLECTION_URL)
    dep_name = url.netloc + url.path.removesuffix(".git")
    rules = json5.loads(RENOVATE_CONFIG.read_text())["packageRules"]

    disabling = [
        rule
        for rule in rules
        if rule.get("enabled") is False and "ansible-galaxy" in rule.get("matchManagers", []) and dep_name in rule.get("matchDepNames", [])
    ]

    assert disabling
