"""How the Renovate config check is wired into CI: the job that runs it, the filter that
queues it, and the pin it reads. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from ci.gates import renovate_config as rc
from ci.images import remote as rm

REPO_ROOT = Path(__file__).resolve().parents[4]
PR_CHECKS = REPO_ROOT / ".github/workflows/pr-checks.yml"
FILTERS = REPO_ROOT / ".github/detect-changes-filters.yml"
COMMAND = "python3 -m ci.gates.renovate_config"


@pytest.fixture(scope="module")
def pr_checks():
    return yaml.safe_load(PR_CHECKS.read_text())


@pytest.fixture(scope="module")
def job(pr_checks):
    return pr_checks["jobs"]["renovate-config-check"]


@pytest.fixture(scope="module")
def filters():
    return yaml.safe_load(FILTERS.read_text())["renovate_config"]


def check_step(job):
    (step,) = [step for step in job["steps"] if step.get("run") == COMMAND]
    return step


class TestJob:
    def test_it_runs_only_when_the_filter_matched(self, job):
        assert job["if"] == "needs.detect-changes.outputs.renovate_config == 'true'"
        assert job["needs"] == "detect-changes"

    def test_detect_changes_passes_the_filters_verdict_on(self, pr_checks):
        outputs = pr_checks["jobs"]["detect-changes"]["outputs"]
        assert outputs["renovate_config"] == "${{ steps.filter.outputs.renovate_config }}"

    def test_the_check_runs_with_plain_python3_from_tools(self, job):
        assert check_step(job)["working-directory"] == "tools"

    def test_the_job_holds_no_credential(self, job):
        assert "env" not in check_step(job)
        (checkout,) = [step for step in job["steps"] if step.get("name") == "Checkout"]
        assert checkout["with"] == {"persist-credentials": False}

    def test_the_run_is_bounded(self, job):
        assert job["timeout-minutes"] <= 15

    def test_it_is_not_a_matrix_job_so_it_can_be_required_directly(self, job):
        assert "strategy" not in job


class TestFilter:
    @pytest.mark.parametrize(
        "path",
        [
            pytest.param(rc.CONFIG, id="the-config"),
            pytest.param(rc.WORKFLOW, id="the-workflow-holding-the-pin"),
            pytest.param("tools/ci/gates/renovate_config.py", id="the-check"),
        ],
    )
    def test_a_change_to_what_the_check_reads_matches(self, filters, path):
        assert path in filters


class TestPin:
    def test_the_check_runs_the_image_renovate_tracks_and_the_scheduled_run_uses(self):
        pins = rm.collect(REPO_ROOT).images
        image = rc.pinned_image((REPO_ROOT / rc.WORKFLOW).read_text())
        assert pins[image] == [rc.WORKFLOW]
