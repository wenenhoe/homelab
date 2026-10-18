"""How the shell tests and their pin check run: on a pull request that touches a shell script, a shell test or a pin.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
PR_CHECKS = REPO_ROOT / ".github/workflows/pr-checks.yml"
WEEKLY = REPO_ROOT / ".github/workflows/check-shell-test-pins.yml"
FILTERS = REPO_ROOT / ".github/detect-changes-filters.yml"
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__"}


@pytest.fixture(scope="module")
def pr_checks():
    return yaml.safe_load(PR_CHECKS.read_text())


@pytest.fixture(scope="module")
def filters():
    return yaml.safe_load(FILTERS.read_text())


@pytest.fixture(scope="module")
def weekly():
    return yaml.safe_load(WEEKLY.read_text())


@pytest.fixture(scope="module")
def job(pr_checks):
    return pr_checks["jobs"]["shell-tests"]


def step_running(job, command):
    (step,) = [step for step in job["steps"] if step.get("run", "").startswith(command)]
    return step


def shell_scripts():
    found = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        found += [Path(dirpath, name).relative_to(REPO_ROOT).as_posix() for name in filenames if name.endswith((".sh", ".sh.j2"))]
    return sorted(found)


class TestJob:
    def test_it_runs_only_when_the_filter_matched(self, job):
        assert (job["needs"], job["if"]) == ("detect-changes", "needs.detect-changes.outputs.shell_tests == 'true'")

    def test_detect_changes_passes_both_verdicts_on(self, pr_checks):
        outputs = pr_checks["jobs"]["detect-changes"]["outputs"]
        assert (outputs["shell_tests"], outputs["shell_test_pins"]) == (
            "${{ steps.filter.outputs.shell_tests }}",
            "${{ steps.filter.outputs.shell_test_pins }}",
        )

    def test_it_is_not_a_matrix_job_so_it_can_be_required_directly(self, job):
        assert "strategy" not in job

    def test_the_run_is_bounded(self, job):
        assert job["timeout-minutes"] <= 15

    def test_it_installs_nothing_but_the_checkout(self, job):
        assert [step["uses"].split("@")[0] for step in job["steps"] if "uses" in step] == ["actions/checkout"]

    def test_the_checkout_keeps_no_credential(self, job):
        (checkout,) = [step for step in job["steps"] if "uses" in step]
        assert checkout["with"] == {"persist-credentials": False}

    def test_the_clones_are_fetched_with_plain_python3_from_tools_into_the_runners_temp_directory(self, job):
        step = step_running(job, "python3 -m ci.shell_tests.fetch")
        assert (step["run"], step["working-directory"]) == ('python3 -m ci.shell_tests.fetch "$RUNNER_TEMP/bats"', "tools")

    def test_bats_runs_from_the_fetched_clone_on_the_fetched_libraries(self, job):
        run = step_running(job, 'BATS_LIB_PATH="$RUNNER_TEMP/bats"')["run"]
        assert run == 'BATS_LIB_PATH="$RUNNER_TEMP/bats" "$RUNNER_TEMP/bats/bats-core/bin/bats" --print-output-on-failure tools/tests/shell'

    def test_the_run_and_the_fetch_wait_for_a_suite_to_exist(self, job):
        steps = [step_running(job, "python3 -m ci.shell_tests.fetch"), step_running(job, 'BATS_LIB_PATH="$RUNNER_TEMP/bats"')]
        assert [step["if"] for step in steps] == ["steps.suite.outputs.present == 'true'"] * 2

    def test_the_pin_check_runs_only_when_the_pins_or_their_tooling_changed(self, job):
        step = step_running(job, "python3 -m ci.shell_tests.pins check")
        assert (step["if"], step["working-directory"]) == ("needs.detect-changes.outputs.shell_test_pins == 'true'", "tools")

    def test_no_secret_reaches_it(self):
        assert "secrets." not in PR_CHECKS.read_text().split("  shell-tests:")[1].split("  compose-syntax-check:")[0]


class TestWeeklyRun:
    def test_it_runs_once_a_week(self, weekly):
        (entry,) = weekly[True]["schedule"]  # PyYAML reads the bare key `on` as True
        _minute, hour, day_of_month, month, day_of_week = entry["cron"].split()
        assert (day_of_month, month) == ("*", "*")
        assert re.fullmatch(r"[0-6]", day_of_week)
        assert re.fullmatch(r"\d+", hour)

    def test_the_minute_is_not_the_top_of_the_hour(self, weekly):
        assert re.fullmatch(r"[1-9]\d?", weekly[True]["schedule"][0]["cron"].split()[0])

    def test_it_can_also_be_started_by_hand_and_nothing_else_triggers_it(self, weekly):
        assert set(weekly[True]) == {"schedule", "workflow_dispatch"}

    def test_it_has_read_access_only_and_needs_no_secret(self, weekly):
        assert weekly["permissions"] == {"contents": "read"}
        assert "secrets." not in WEEKLY.read_text()

    def test_a_second_run_never_overlaps_or_cancels_the_first(self, weekly):
        assert weekly["concurrency"] == {"group": "check-shell-test-pins", "cancel-in-progress": False}

    def test_the_run_is_bounded(self, weekly):
        assert weekly["jobs"]["check-shell-test-pins"]["timeout-minutes"] <= 15

    def test_the_check_runs_with_plain_python3_from_tools(self, weekly):
        step = step_running(weekly["jobs"]["check-shell-test-pins"], "python3")
        assert (step["run"], step["working-directory"]) == ("python3 -m ci.shell_tests.pins check", "tools")

    def test_the_checkout_keeps_no_credential(self, weekly):
        (checkout,) = [step for step in weekly["jobs"]["check-shell-test-pins"]["steps"] if "uses" in step]
        assert checkout["with"] == {"persist-credentials": False}

    def test_it_runs_the_same_command_as_the_pull_request_job(self, weekly, job):
        weekly_step = step_running(weekly["jobs"]["check-shell-test-pins"], "python3")
        assert weekly_step["run"] == step_running(job, "python3 -m ci.shell_tests.pins")["run"]


class TestSuiteLookup:
    def lookup(self, job):
        return step_running(job, "if [ -n")

    def test_it_looks_for_a_bats_file_under_the_suite_directory(self, job):
        assert "find tools/tests/shell -name '*.bats'" in self.lookup(job)["run"]

    def test_it_reports_the_answer_as_a_step_output(self, job):
        step = self.lookup(job)
        assert (step["id"], step["run"].count('>> "$GITHUB_OUTPUT"')) == ("suite", 2)


class TestFilters:
    @pytest.mark.parametrize("path", shell_scripts())
    def test_every_shell_script_and_template_in_the_tree_matches(self, path, filters):
        assert any(PurePosixPath(path).full_match(glob) for glob in filters["shell_tests"])

    @pytest.mark.parametrize(
        "path",
        [
            "tools/tests/shell/run_restore.bats",
            "tools/tests/shell/test_helper/harness.bash",
            "tools/ci/shell_tests/pins.txt",
            "tools/ci/shell_tests/fetch.py",
            "tools/ci/verification.py",
            "script.sh",
            "ansible/roles/x/templates/check.sh.j2",
        ],
    )
    def test_the_tests_the_pins_and_a_script_at_any_depth_match(self, path, filters):
        assert any(PurePosixPath(path).full_match(glob) for glob in filters["shell_tests"])

    @pytest.mark.parametrize("path", ["docs/topics/README.md", "ansible/roles/x/tasks/main.yaml", "tools/ci/images/remote.py", "docker/caddy/Dockerfile"])
    def test_a_change_with_no_shell_in_it_does_not_match(self, path, filters):
        assert not any(PurePosixPath(path).full_match(glob) for glob in filters["shell_tests"])

    def test_the_pin_filter_is_the_pin_file_and_what_checks_and_fetches_it(self, filters):
        assert filters["shell_test_pins"] == ["tools/ci/shell_tests/**", "tools/ci/verification.py"]
