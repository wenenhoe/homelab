"""The weekly image-tag check's workflow: once a week, anonymous, read-only.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[4] / ".github/workflows/check-image-tags.yml"


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


@pytest.fixture(scope="module")
def triggers(workflow):
    return workflow[True]  # PyYAML reads the bare key `on` as True


@pytest.fixture(scope="module")
def job(workflow):
    return workflow["jobs"]["check-image-tags"]


class TestWorkflow:
    def test_it_runs_once_a_week(self, triggers):
        (entry,) = triggers["schedule"]
        minute, hour, day_of_month, month, day_of_week = entry["cron"].split()
        assert (day_of_month, month) == ("*", "*")
        assert re.search(r"^[0-6]$", day_of_week)
        assert re.search(r"^\d+$", minute)
        assert re.search(r"^\d+$", hour)

    def test_the_minute_is_not_the_top_of_the_hour(self, triggers):
        assert triggers["schedule"][0]["cron"].split()[0] != "0"

    def test_it_can_also_be_started_by_hand_and_nothing_else_triggers_it(self, triggers):
        assert set(triggers) == {"schedule", "workflow_dispatch"}

    def test_it_needs_no_credentials_and_no_write_access(self, workflow):
        assert workflow["permissions"] == {"contents": "read"}
        text = WORKFLOW.read_text()
        assert "secrets." not in text
        assert "GITHUB_TOKEN" not in text

    def test_a_second_run_never_overlaps_or_cancels_the_first(self, workflow):
        assert workflow["concurrency"] == {"group": "check-image-tags", "cancel-in-progress": False}

    def test_the_run_is_bounded(self, job):
        assert job["timeout-minutes"] <= 15

    def test_the_only_check_step_runs_the_module_with_plain_python3(self, job):
        step = next(step for step in job["steps"] if "run" in step)
        assert step["run"] == "python3 -m ci.images.remote check"
        assert step["working-directory"] == "tools"
