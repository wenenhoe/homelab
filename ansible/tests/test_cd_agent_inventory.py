"""The CD agent's jobs, as the inventory defines them, hold the shape ADR 0074 requires.

The role refuses a bad chain when it provisions the host, which only the
operator does; these fail in review instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from cd_agent_chain import cd_agent_chain_errors

INVENTORY = Path(__file__).resolve().parents[1] / "inventory/group_vars/cd_agent.yaml"


@pytest.fixture(scope="module")
def jobs() -> dict[str, dict]:
    return {job["name"]: job for job in yaml.safe_load(INVENTORY.read_text())["cd_agent_jobs"]}


def test_the_chains_are_valid(jobs):
    assert cd_agent_chain_errors(list(jobs.values())) == []


def test_redeploy_storage_follows_rotation_and_has_no_timer_of_its_own(jobs):
    assert jobs["rotation"]["successors"] == ["redeploy-storage"]
    assert "poll_interval" not in jobs["redeploy-storage"]
    assert "on_calendar" not in jobs["redeploy-storage"]


def test_redeploy_storage_deploys_to_storage_alone_and_without_waiting_for_a_commit(jobs):
    # The redeploy identity reaches storage and the controller play, not every managed host (ADR 0074).
    command = jobs["redeploy-storage"]["command"]

    assert command.count("--limit") == 1
    assert command[command.index("--limit") + 1] == "storage,localhost"
    assert not jobs["redeploy-storage"].get("on_change", False)
