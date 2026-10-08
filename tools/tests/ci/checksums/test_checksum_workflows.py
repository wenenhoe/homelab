"""The two runs of the release checksum check: on a pull request that touches a pin, and weekly.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from ci.checksums.registry import ENTRIES

REPO_ROOT = Path(__file__).resolve().parents[4]
WEEKLY = REPO_ROOT / ".github/workflows/check-release-checksums.yml"
PR_CHECKS = REPO_ROOT / ".github/workflows/pr-checks.yml"
FILTERS = REPO_ROOT / ".github/detect-changes-filters.yml"
COMMAND = "python3 -m ci.checksums.verify"


@pytest.fixture(scope="module")
def weekly():
    return yaml.safe_load(WEEKLY.read_text())


@pytest.fixture(scope="module")
def pr_checks():
    return yaml.safe_load(PR_CHECKS.read_text())


@pytest.fixture(scope="module")
def filters():
    return yaml.safe_load(FILTERS.read_text())["release_checksums"]


@pytest.fixture(scope="module")
def triggers(weekly):
    return weekly[True]  # PyYAML reads the bare key `on` as True


@pytest.fixture(scope="module")
def job(pr_checks):
    return pr_checks["jobs"]["release-checksums"]


def check_step(job):
    (step,) = [step for step in job["steps"] if step.get("run") == COMMAND]
    return step


class TestWeeklyRun:
    def test_it_runs_once_a_week(self, triggers):
        (entry,) = triggers["schedule"]
        _minute, hour, day_of_month, month, day_of_week = entry["cron"].split()
        assert (day_of_month, month) == ("*", "*")
        assert re.fullmatch(r"[0-6]", day_of_week)
        assert re.fullmatch(r"\d+", hour)

    def test_the_minute_is_not_the_top_of_the_hour(self, triggers):
        assert re.fullmatch(r"[1-9]\d?", triggers["schedule"][0]["cron"].split()[0])

    def test_it_can_also_be_started_by_hand_and_nothing_else_triggers_it(self, triggers):
        assert set(triggers) == {"schedule", "workflow_dispatch"}

    def test_it_has_read_access_only(self, weekly):
        assert weekly["permissions"] == {"contents": "read"}

    def test_a_second_run_never_overlaps_or_cancels_the_first(self, weekly):
        assert weekly["concurrency"] == {"group": "check-release-checksums", "cancel-in-progress": False}

    def test_the_run_is_bounded(self, weekly):
        assert weekly["jobs"]["check-release-checksums"]["timeout-minutes"] <= 15

    def test_the_check_runs_with_plain_python3_from_tools(self, weekly):
        step = check_step(weekly["jobs"]["check-release-checksums"])
        assert step["working-directory"] == "tools"

    def test_the_only_credential_is_the_workflows_own_token(self, weekly):
        step = check_step(weekly["jobs"]["check-release-checksums"])
        assert step["env"] == {"GH_TOKEN": "${{ github.token }}"}
        assert "secrets." not in WEEKLY.read_text()


class TestPullRequestRun:
    def test_it_runs_only_when_the_filter_matched(self, job):
        assert job["if"] == "needs.detect-changes.outputs.release_checksums == 'true'"
        assert job["needs"] == "detect-changes"

    def test_detect_changes_passes_the_filters_verdict_on(self, pr_checks):
        outputs = pr_checks["jobs"]["detect-changes"]["outputs"]
        assert outputs["release_checksums"] == "${{ steps.filter.outputs.release_checksums }}"

    def test_the_check_runs_with_plain_python3_from_tools(self, job):
        assert check_step(job)["working-directory"] == "tools"

    def test_the_only_credential_is_the_workflows_own_token(self, job):
        assert check_step(job)["env"] == {"GH_TOKEN": "${{ github.token }}"}

    def test_the_run_is_bounded(self, job):
        assert job["timeout-minutes"] <= 15

    def test_it_is_not_a_matrix_job_so_it_can_be_required_directly(self, job):
        assert "strategy" not in job


class TestFilter:
    def test_a_change_to_the_check_or_its_keys_matches(self, filters):
        assert "tools/ci/checksums/**" in filters

    @pytest.mark.parametrize("entry", ENTRIES, ids=lambda entry: entry.name)
    def test_a_change_to_the_file_holding_an_entrys_pin_matches(self, entry, filters):
        assert entry.pin.path in filters

    @pytest.mark.parametrize("entry", ENTRIES, ids=lambda entry: entry.name)
    def test_and_to_the_file_holding_its_version(self, entry, filters):
        assert entry.version.path in filters
