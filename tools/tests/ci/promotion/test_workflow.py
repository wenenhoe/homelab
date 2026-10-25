"""The checklist workflow is advice that cannot be turned into a way in (ADR 0076).

It holds a write token on pull requests, so it runs main's code and checks
nothing out of the pull request; and it is not a check any ruleset waits on.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = ROOT / ".github/workflows/promotion-checklist.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


@pytest.fixture(scope="module")
def triggers(workflow) -> dict:
    return workflow.get("on", workflow.get(True))


def test_it_runs_on_pull_requests_into_main_only(triggers):
    assert list(triggers) == ["pull_request_target"]
    assert triggers["pull_request_target"]["branches"] == ["main"]


def test_it_runs_when_the_diff_changes(triggers):
    assert set(triggers["pull_request_target"]["types"]) == {"opened", "synchronize", "reopened"}


def test_the_write_permission_is_the_one_job_s_alone(workflow, subtests):
    with subtests.test("the workflow grants nothing"):
        assert workflow["permissions"] == {}
    with subtests.test("the job gets contents read and pull request write"):
        assert workflow["jobs"]["checklist"]["permissions"] == {"contents": "read", "pull-requests": "write"}


def test_nothing_of_the_pull_request_is_checked_out_or_run(workflow, subtests):
    text = WORKFLOW.read_text()
    steps = workflow["jobs"]["checklist"]["steps"]
    checkout = next(step for step in steps if "actions/checkout" in step.get("uses", ""))
    with subtests.test("the checkout takes no ref, so it is main"):
        assert "ref" not in checkout.get("with", {})
    with subtests.test("it keeps no credential"):
        assert checkout["with"]["persist-credentials"] is False
    with subtests.test("no head ref or sha is read anywhere"):
        assert "pull_request.head" not in text
        assert "github.head_ref" not in text


def test_event_values_reach_the_script_through_the_environment(workflow):
    run = next(step["run"] for step in workflow["jobs"]["checklist"]["steps"] if "run" in step)
    assert "${{" not in run


def test_it_runs_the_stdlib_module_on_the_runners_python(workflow):
    run = next(step["run"] for step in workflow["jobs"]["checklist"]["steps"] if "run" in step)
    assert "python3 -m ci.promotion.checklist" in run
    assert "uv run" not in run
