"""Renovate runs against a `maintenance` that has been realigned with `main` (ADR 0076).

The realignment is the first thing the job does after checkout, and nothing lets
the run carry on when it fails: a Renovate run on a branch that is behind main
would open pull requests against code production no longer has.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from ci import json5

ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = ROOT / ".github/workflows/renovate.yml"
CONFIG = ROOT / ".github/renovate.json5"


@pytest.fixture(scope="module")
def steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["renovate"]["steps"]


def _index(steps: list[dict], needle: str) -> int:
    return next(i for i, step in enumerate(steps) if needle in (step.get("uses", "") + step.get("run", "")))


class TestRealignFirst:
    def test_it_runs_after_checkout_and_before_renovate(self, steps):
        assert _index(steps, "actions/checkout") < _index(steps, "ci.branches.realign") < _index(steps, "renovatebot/github-action")

    def test_the_checkout_has_full_history(self, steps):
        assert steps[_index(steps, "actions/checkout")]["with"]["fetch-depth"] == 0

    def test_a_failure_stops_the_run(self, steps, subtests):
        realign = steps[_index(steps, "ci.branches.realign")]
        renovate = steps[_index(steps, "renovatebot/github-action")]
        with subtests.test("the realignment is not allowed to fail quietly"):
            assert "continue-on-error" not in realign
            assert "if" not in realign
        with subtests.test("Renovate runs only after every earlier step succeeded"):
            assert "if" not in renovate

    def test_the_push_uses_the_renovate_token_not_the_default_one(self, steps, subtests):
        realign = steps[_index(steps, "ci.branches.realign")]
        with subtests.test("the token is the Renovate one"):
            assert realign["env"]["RENOVATE_TOKEN"] == "${{ secrets.RENOVATE_TOKEN }}"
        with subtests.test("it is not put on the command line or written to config"):
            assert "git config" not in realign["run"]
            assert "--token" not in realign["run"]
        with subtests.test("the checkout does not keep a credential"):
            assert steps[_index(steps, "actions/checkout")]["with"]["persist-credentials"] is False

    def test_the_workflow_never_forces_a_push(self):
        assert not re.search(r"--force|--mirror|push\s+\S+\s+\+", WORKFLOW.read_text())


@pytest.fixture(scope="module")
def config() -> dict:
    return json5.loads(CONFIG.read_text())


class TestConfigTargetsMaintenance:
    def test_renovate_is_based_on_maintenance(self, config):
        assert config["baseBranchPatterns"] == ["maintenance"]

    def test_a_branch_is_rebased_only_when_maintenance_moved(self, config):
        assert config["rebaseWhen"] == "behind-base-branch"

    def test_control_the_parser_sees_real_keys(self, config):
        assert json.dumps(config["gitAuthor"]).startswith('"wenenhoe')
