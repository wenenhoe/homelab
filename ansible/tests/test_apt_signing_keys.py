"""Each apt signing key a role downloads is installed only after its fingerprint is checked against a pin.

The checks themselves are gpg_keys.gpg_primary_fingerprints (test_gpg_keys.py) and
the assert task in each role; these tests hold the pieces together.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
ROLES = REPO / "ansible/roles"
FINGERPRINT = re.compile(r"[0-9A-F]{40}")


def _load(path: Path):
    return yaml.safe_load(path.read_text())


KEYS = [
    pytest.param("docker", "tasks/main.yaml", "docker_apt_key_fingerprint", "docker_apt_key_staged", "/etc/apt/keyrings/docker.asc", id="docker"),
    pytest.param(
        "tailscale_node",
        "tasks/install.yaml",
        "tailscale_node_apt_key_fingerprint",
        "tailscale_node_apt_key_staged",
        "/etc/apt/keyrings/tailscale.gpg",
        id="tailscale",
    ),
]


@pytest.mark.parametrize(("role", "tasks_file", "pin", "register", "dest"), KEYS)
def test_the_pin_is_a_full_uppercase_fingerprint(role, tasks_file, pin, register, dest):
    defaults = _load(ROLES / role / "defaults/main.yaml")

    assert FINGERPRINT.fullmatch(defaults[pin])


@pytest.mark.parametrize(("role", "tasks_file", "pin", "register", "dest"), KEYS)
def test_the_key_is_downloaded_checked_and_only_then_installed(role, tasks_file, pin, register, dest):
    tasks = _load(ROLES / role / tasks_file)
    download = next(i for i, t in enumerate(tasks) if "ansible.builtin.get_url" in t and t["ansible.builtin.get_url"]["dest"] == f"{dest}.fetched")
    read = next(i for i, t in enumerate(tasks) if t.get("register") == register)
    check = next(i for i, t in enumerate(tasks) if "ansible.builtin.assert" in t and f"{register}.stdout" in t["ansible.builtin.assert"]["that"][0])
    install = next(i for i, t in enumerate(tasks) if "ansible.builtin.copy" in t and t["ansible.builtin.copy"]["dest"] == dest)

    assert download < read < check < install


@pytest.mark.parametrize(("role", "tasks_file", "pin", "register", "dest"), KEYS)
def test_the_check_compares_the_primary_keys_to_exactly_the_pin(role, tasks_file, pin, register, dest):
    tasks = _load(ROLES / role / tasks_file)
    check = next(t for t in tasks if "ansible.builtin.assert" in t and f"{register}.stdout" in t["ansible.builtin.assert"]["that"][0])

    assert check["ansible.builtin.assert"]["that"] == [f"{register}.stdout | gpg_primary_fingerprints == [{pin}]"]


@pytest.mark.parametrize(("role", "tasks_file", "pin", "register", "dest"), KEYS)
def test_the_installed_key_is_the_staged_file_and_nothing_downloaded_straight_to_it(role, tasks_file, pin, register, dest):
    tasks = _load(ROLES / role / tasks_file)
    install = next(t for t in tasks if "ansible.builtin.copy" in t and t["ansible.builtin.copy"]["dest"] == dest)
    straight = [t for t in tasks if "ansible.builtin.get_url" in t and t["ansible.builtin.get_url"]["dest"] == dest]

    assert install["ansible.builtin.copy"]["src"] == f"{dest}.fetched"
    assert straight == []


def test_the_image_built_for_molecule_checks_the_same_docker_fingerprint_as_the_role():
    pinned = _load(ROLES / "docker/defaults/main.yaml")["docker_apt_key_fingerprint"]
    dockerfile = (REPO / "docker/molecule-dind/Dockerfile").read_text()

    assert re.findall(r"= ([0-9A-F]{40}) ", dockerfile) == [pinned]
