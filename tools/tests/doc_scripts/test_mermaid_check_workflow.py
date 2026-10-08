"""How the Mermaid render check is wired into CI: the job that runs it, the filter that
queues it, and the Renovate manager that keeps its image current. Run via
`uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from ci.images import remote as rm
from doc_scripts import check_mermaid

REPO_ROOT = Path(__file__).resolve().parents[3]
PR_CHECKS = REPO_ROOT / ".github/workflows/pr-checks.yml"
FILTERS = REPO_ROOT / ".github/detect-changes-filters.yml"
COMMAND = "python3 -m doc_scripts.check_mermaid"


@pytest.fixture(scope="module")
def pr_checks():
    return yaml.safe_load(PR_CHECKS.read_text())


@pytest.fixture(scope="module")
def job(pr_checks):
    return pr_checks["jobs"]["mermaid-check"]


@pytest.fixture(scope="module")
def filters():
    return yaml.safe_load(FILTERS.read_text())["mermaid_check"]


@pytest.fixture(scope="module")
def pins():
    return rm.collect(REPO_ROOT).images


def check_step(job):
    (step,) = [step for step in job["steps"] if step.get("run") == COMMAND]
    return step


class TestJob:
    def test_it_runs_only_when_the_filter_matched(self, job):
        assert job["if"] == "needs.detect-changes.outputs.mermaid_check == 'true'"
        assert job["needs"] == "detect-changes"

    def test_detect_changes_passes_the_filters_verdict_on(self, pr_checks):
        outputs = pr_checks["jobs"]["detect-changes"]["outputs"]
        assert outputs["mermaid_check"] == "${{ steps.filter.outputs.mermaid_check }}"

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
    def test_a_change_to_any_markdown_file_matches(self, filters):
        assert "**/*.md" in filters

    def test_a_change_to_the_check_matches_because_its_file_holds_the_image(self, filters):
        assert "tools/doc_scripts/check_mermaid.py" in filters


class TestImagePin:
    def test_renovate_tracks_the_image_the_check_runs(self, pins):
        assert check_mermaid.MERMAID_CLI_IMAGE in pins
        assert pins[check_mermaid.MERMAID_CLI_IMAGE] == ["tools/doc_scripts/check_mermaid.py"]
