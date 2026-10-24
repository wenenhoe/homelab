"""The progress log's workflow: daily, one write token, pushed only to the progress-log branch (ADR 0095).

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github/workflows/progress-log.yml"
FORCE = re.compile(r"--force|--force-with-lease|--delete|\s-f\s|\s\+\S+:|\s:\S+")


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


@pytest.fixture(scope="module")
def jobs(workflow):
    return workflow["jobs"]


@pytest.fixture(scope="module")
def pushes(jobs):
    return [
        line.strip() for job in jobs.values() for step in job["steps"] for line in step.get("run", "").splitlines() if re.search(r"\bgit\b.*\bpush\b", line)
    ]


class TestTriggers:
    def test_it_runs_on_a_schedule_and_by_hand_and_on_nothing_else(self, workflow):
        assert set(workflow[True]) == {"schedule", "workflow_dispatch"}  # PyYAML reads the bare key `on` as True

    def test_it_runs_every_day_at_a_fixed_time_off_the_hour(self, workflow):
        (entry,) = workflow[True]["schedule"]
        minute, hour, day_of_month, month, day_of_week = entry["cron"].split()
        assert (minute.isdigit() and minute != "0", hour.isdigit(), (day_of_month, month, day_of_week)) == (True, True, ("*", "*", "*"))

    def test_a_second_run_never_overlaps_or_cancels_the_first(self, workflow):
        assert workflow["concurrency"] == {"group": "progress-log", "cancel-in-progress": False}


class TestPermissions:
    def test_the_workflow_as_a_whole_can_only_read(self, workflow):
        assert workflow["permissions"] == {"contents": "read"}

    def test_contents_write_is_on_the_publishing_job_alone(self, jobs):
        writers = [name for name, job in jobs.items() if "write" in job.get("permissions", {}).values()]
        assert writers == ["publish"]

    def test_the_publishing_job_asks_for_nothing_else(self, jobs):
        assert jobs["publish"]["permissions"] == {"contents": "write"}

    def test_no_checkout_stores_the_token(self, jobs, subtests):
        checkouts = [step for step in jobs["publish"]["steps"] if step.get("uses", "").startswith("actions/checkout@")]
        for step in checkouts:
            with subtests.test(path=step["with"]["path"]):
                assert step["with"]["persist-credentials"] is False

    def test_no_secret_other_than_the_job_token_is_used(self):
        assert re.findall(r"secrets\.\w+", WORKFLOW.read_text()) == []


class TestPush:
    def test_it_pushes_once_and_only_to_the_progress_log_branch(self, pushes):
        assert len(pushes) == 1 and pushes[0].endswith("push origin HEAD:refs/heads/progress-log")

    def test_the_push_neither_forces_nor_deletes(self, pushes):
        assert not FORCE.search(f" {pushes[0]} ")

    def test_main_is_checked_out_to_read_not_to_write(self, jobs):
        step = next(step for step in jobs["publish"]["steps"] if step["name"] == "Checkout main")
        assert (step["with"]["ref"], step["with"]["fetch-depth"]) == ("main", 0)

    def test_the_branch_it_writes_to_must_already_exist(self, jobs):
        step = next(step for step in jobs["publish"]["steps"] if step["name"] == "Checkout the progress-log branch")
        assert step["with"]["ref"] == "progress-log"

    def test_it_commits_only_inside_the_log_checkout(self, jobs):
        step = next(step for step in jobs["publish"]["steps"] if "git add" in step.get("run", ""))
        assert step["working-directory"] == "log"


class TestGenerator:
    def test_it_runs_the_module_with_plain_python3_from_tools(self, jobs):
        step = next(step for step in jobs["publish"]["steps"] if "progress_log" in step.get("run", ""))
        assert (step["run"].split()[:3], step["working-directory"]) == (["python3", "-m", "progress_log"], "main/tools")

    def test_the_module_it_names_exists(self):
        assert (REPO_ROOT / "tools/progress_log/__main__.py").is_file()
