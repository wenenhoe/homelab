"""Every fwupdmgr call in the fwupd role accepts exit code 2, its "nothing to do" result.

A host with no firmware fwupd can update, such as a VM, gets that code from `update`.
Failing there would stop maintenance.yaml before the hosts after it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ANSIBLE = Path(__file__).resolve().parents[1]


@pytest.fixture
def tasks() -> dict[str, dict]:
    items = yaml.safe_load((ANSIBLE / "roles/fwupd/tasks/main.yaml").read_text())
    return {item["name"]: item for item in items}


@pytest.mark.parametrize(
    ("task", "register"),
    [
        pytest.param("Refresh fwupd metadata cache", "fwupd_refresh", id="refresh"),
        pytest.param("Check for available firmware upgrades", "fwupd_updates", id="get-upgrades"),
        pytest.param("Apply firmware updates if available", "fwupd_upgrade", id="update"),
        pytest.param("Check if a reboot is required to apply firmware", "fwupd_reboot_check", id="check-reboot-needed"),
    ],
)
def test_a_fwupdmgr_call_fails_only_on_an_exit_code_other_than_ok_or_nothing_to_do(tasks, task, register):
    assert tasks[task]["failed_when"] == f"{register}.rc not in [0, 2]"
