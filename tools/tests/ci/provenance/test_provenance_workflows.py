"""The two runs of the image provenance check: on a pull request that touches an image
reference, and weekly. Also the filter that queues the first, and the pin on the image
that runs cosign.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

import pytest
import yaml
from ci.images import remote
from ci.provenance import verify

REPO_ROOT = Path(__file__).resolve().parents[4]
WEEKLY = REPO_ROOT / ".github/workflows/check-image-provenance.yml"
PR_CHECKS = REPO_ROOT / ".github/workflows/pr-checks.yml"
FILTERS = REPO_ROOT / ".github/detect-changes-filters.yml"
COMMAND = "python3 -m ci.provenance.verify"


@pytest.fixture(scope="module")
def weekly():
    return yaml.safe_load(WEEKLY.read_text())


@pytest.fixture(scope="module")
def pr_checks():
    return yaml.safe_load(PR_CHECKS.read_text())


@pytest.fixture(scope="module")
def filters():
    return yaml.safe_load(FILTERS.read_text())["image_provenance"]


@pytest.fixture(scope="module")
def triggers(weekly):
    return weekly[True]  # PyYAML reads the bare key `on` as True


@pytest.fixture(scope="module")
def job(pr_checks):
    return pr_checks["jobs"]["provenance"]


@pytest.fixture(scope="module")
def collected():
    return remote.collect(REPO_ROOT)


def check_step(job):
    (step,) = [step for step in job["steps"] if step.get("run") == COMMAND]
    return step


class TestWeeklyRun:
    def test_it_runs_once_a_week_off_the_top_of_the_hour(self, triggers):
        (entry,) = triggers["schedule"]
        minute, hour, day_of_month, month, day_of_week = entry["cron"].split()
        assert (day_of_month, month) == ("*", "*")
        assert re.fullmatch(r"[0-6]", day_of_week)
        assert re.fullmatch(r"\d+", hour)
        assert re.fullmatch(r"[1-9]\d?", minute)

    def test_it_can_also_be_started_by_hand_and_nothing_else_triggers_it(self, triggers):
        assert set(triggers) == {"schedule", "workflow_dispatch"}

    def test_it_has_read_access_only(self, weekly):
        assert weekly["permissions"] == {"contents": "read"}

    def test_a_second_run_never_overlaps_or_cancels_the_first(self, weekly):
        assert weekly["concurrency"] == {"group": "check-image-provenance", "cancel-in-progress": False}

    def test_the_run_is_bounded(self, weekly):
        assert weekly["jobs"]["check-image-provenance"]["timeout-minutes"] <= 15

    def test_the_check_runs_with_plain_python3_from_tools(self, weekly):
        assert check_step(weekly["jobs"]["check-image-provenance"])["working-directory"] == "tools"

    def test_the_only_credential_is_the_workflows_own_token(self, weekly):
        assert check_step(weekly["jobs"]["check-image-provenance"])["env"] == {"GH_TOKEN": "${{ github.token }}"}
        assert "secrets." not in WEEKLY.read_text()

    def test_the_check_is_the_only_command_the_job_runs_so_nothing_is_installed(self, weekly):
        assert [step["run"] for step in weekly["jobs"]["check-image-provenance"]["steps"] if "run" in step] == [COMMAND]


class TestPullRequestRun:
    def test_it_runs_only_when_the_filter_matched(self, job):
        assert job["if"] == "needs.detect-changes.outputs.image_provenance == 'true'"
        assert job["needs"] == "detect-changes"

    def test_detect_changes_passes_the_filters_verdict_on(self, pr_checks):
        assert pr_checks["jobs"]["detect-changes"]["outputs"]["image_provenance"] == "${{ steps.filter.outputs.image_provenance }}"

    def test_the_check_runs_with_plain_python3_from_tools(self, job):
        assert check_step(job)["working-directory"] == "tools"

    def test_the_only_credential_is_the_workflows_own_token(self, job):
        assert check_step(job)["env"] == {"GH_TOKEN": "${{ github.token }}"}
        (checkout,) = [step for step in job["steps"] if step.get("name") == "Checkout"]
        assert checkout["with"] == {"persist-credentials": False}

    def test_the_run_is_bounded(self, job):
        assert job["timeout-minutes"] <= 15

    def test_the_check_is_the_only_command_the_job_runs_so_nothing_is_installed(self, job):
        assert [step["run"] for step in job["steps"] if "run" in step] == [COMMAND]

    def test_it_is_not_a_matrix_job_so_it_can_be_required_directly(self, job):
        assert "strategy" not in job


class TestFilter:
    def test_a_change_to_the_check_its_registry_or_its_keys_matches(self, filters):
        assert "tools/ci/provenance/**" in filters

    def test_a_change_to_the_verifier_calls_it_shares_with_the_checksum_check_matches(self, filters):
        assert "tools/ci/verification.py" in filters

    def test_a_change_to_any_file_that_pins_an_image_matches(self, collected, filters, subtests):
        sources = sorted({source for files in collected.images.values() for source in files})
        assert sources
        for source in sources:
            with subtests.test(source=source):
                assert any(PurePosixPath(source).full_match(glob) for glob in filters)


class TestCosignImage:
    def test_it_is_pinned_by_digest(self):
        assert re.fullmatch(r"ghcr\.io/sigstore/cosign/cosign:v\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", verify.COSIGN_IMAGE)

    def test_it_is_version_3_or_later(self):
        assert int(verify.COSIGN_IMAGE.split(":v")[1].split(".")[0]) >= 3

    def test_renovate_tracks_the_image_the_check_runs(self, collected):
        assert collected.images[verify.COSIGN_IMAGE] == ["tools/ci/provenance/verify.py"]
        assert collected.problems == []
