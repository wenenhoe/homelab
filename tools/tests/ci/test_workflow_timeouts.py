"""Every job in every workflow bounds its own run time.

A job without `timeout-minutes` runs until GitHub's six-hour default, so a
hung step holds its runner, and one of the account's concurrent job slots,
that long. A job that calls a reusable workflow (`uses:`) can't set one: the
jobs of the workflow it calls carry their own.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github/workflows"


def _step_running_jobs():
    return [
        pytest.param(job, id=f"{path.name}:{name}")
        for path in sorted(WORKFLOWS.glob("*.yml"))
        for name, job in yaml.safe_load(path.read_text())["jobs"].items()
        if "uses" not in job
    ]


@pytest.mark.parametrize("job", _step_running_jobs())
def test_a_job_that_runs_steps_sets_a_timeout(job):
    assert isinstance(job.get("timeout-minutes"), int)
