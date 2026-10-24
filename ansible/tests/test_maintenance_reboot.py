"""maintenance.yaml upgrades `security` but never reboots it, and reboots the other hosts one at a time.

A reboot of `security` seals OpenBao until someone supplies the unseal shares,
which the unattended maintenance job cannot do (ADR 0018).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ANSIBLE = Path(__file__).resolve().parents[1]
GATE = "patch_reboot_allowed | default(true) | bool"


def _load(relative: str):
    return yaml.safe_load((ANSIBLE / relative).read_text())


def test_security_is_upgraded_but_not_rebooted():
    assert _load("inventory/host_vars/security.yaml")["patch_reboot_allowed"] is False


def test_no_other_host_turns_rebooting_off():
    others = [
        path.name
        for path in (ANSIBLE / "inventory/host_vars").glob("*.yaml")
        if path.stem != "security" and "patch_reboot_allowed" in _load(f"inventory/host_vars/{path.name}")
    ]

    assert others == []


def test_the_patching_play_takes_one_host_at_a_time():
    play = next(play for play in _load("playbooks/maintenance.yaml") if play.get("hosts") == "patched_hosts" and play.get("roles"))

    assert play["serial"] == 1
    assert play["roles"] == ["apt", "fwupd"]


@pytest.mark.parametrize(
    ("role", "task"),
    [
        pytest.param("apt", "Reboot the server if required", id="apt"),
        pytest.param("fwupd", "Reboot the machine to apply offline firmware capsules", id="fwupd"),
    ],
)
def test_each_roles_reboot_waits_for_the_hosts_permission(role, task):
    reboot = next(item for item in _load(f"roles/{role}/tasks/main.yaml") if item.get("name") == task)

    assert GATE in reboot["when"]
