"""A pull request into any of the three long-lived branches runs the same checks (ADR 0076).

A check that does not run for a branch never reports there, so a ruleset that
requires it leaves every pull request into that branch pending. The checks
are the jobs of the workflows that trigger on `pull_request`.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[4] / ".github/workflows"
BRANCHES = ("main", "maintenance", "develop")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _triggers(workflow: dict) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    on = workflow.get("on", workflow.get(True))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(on)
    return on


def _conditions(workflow: dict) -> list[str]:
    conditions = []
    for job in workflow["jobs"].values():
        conditions.append(job.get("if"))
        conditions.extend(step.get("if") for step in job.get("steps", []))
    return [str(condition) for condition in conditions if condition is not None]


PULL_REQUEST_WORKFLOWS = [pytest.param(path, id=path.name) for path in sorted(WORKFLOWS.glob("*.yml")) if "pull_request" in _triggers(_load(path))]


def test_pr_checks_is_among_the_workflows_that_run_on_pull_requests():
    assert "pr-checks.yml" in [param.id for param in PULL_REQUEST_WORKFLOWS]


@pytest.mark.parametrize("path", PULL_REQUEST_WORKFLOWS)
def test_a_pull_request_into_each_long_lived_branch_runs_the_workflow(path):
    pull_request = _triggers(_load(path))["pull_request"] or {}
    branches = pull_request.get("branches")
    assert "branches-ignore" not in pull_request
    assert branches is None or set(BRANCHES) <= set(branches), f"{path.name} runs for {branches}, not all of {list(BRANCHES)}"


@pytest.mark.parametrize("path", PULL_REQUEST_WORKFLOWS)
def test_no_job_or_step_runs_only_for_one_base_branch(path, subtests):
    for condition in _conditions(_load(path)):
        with subtests.test(condition=condition):
            assert "base_ref" not in condition
            assert "base.ref" not in condition
