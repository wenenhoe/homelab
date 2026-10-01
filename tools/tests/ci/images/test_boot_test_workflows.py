"""How the two callers of the reusable boot-test workflow differ (ADR 0064 layout, docs/topics/engineering/ci.md#dockerfile-changes).

A PR boots the Dockerfile it changed, because that image isn't published until
after merge. A full sweep boots the published images instead, so it also
fails when a compose pin's tag was never pushed. The switch is one input.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[4] / ".github/workflows"


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


@pytest.fixture(scope="module")
def reusable():
    return load("_compose-boot-test.yml")


@pytest.fixture(scope="module")
def inputs(reusable):
    return reusable[True]["workflow_call"]["inputs"]  # PyYAML reads the bare key `on` as True


@pytest.fixture(scope="module")
def steps(reusable):
    return reusable["jobs"]["compose-boot-test"]["steps"]


class TestBootTestWorkflow:
    def test_the_input_is_an_optional_boolean_that_defaults_on(self, inputs):
        spec = inputs["build-dockerfiles"]
        assert spec["type"] == "boolean"
        assert spec["default"] is True
        assert not spec["required"]

    def test_only_the_dockerfile_build_step_is_gated_on_it(self, steps):
        gated = [step["name"] for step in steps if step.get("if") == "inputs.build-dockerfiles"]
        assert len(gated) == 1
        assert "Dockerfile" in gated[0]
        step = next(step for step in steps if step.get("if") == "inputs.build-dockerfiles")
        assert "ci.images.build shadow-tag" in step["run"]

    def test_a_pr_takes_the_default_and_builds_its_dockerfiles(self):
        job = load("pr-checks.yml")["jobs"]["compose-boot-test"]
        assert "build-dockerfiles" not in job["with"]

    def test_the_full_sweep_boots_the_published_images(self):
        job = load("boot-test-all.yml")["jobs"]["compose-boot-test-all"]
        assert job["with"]["build-dockerfiles"] is False

    def test_the_full_sweep_stays_manual_only(self):
        triggers = load("boot-test-all.yml")[True]
        assert set(triggers) == {"workflow_dispatch"}

    def test_every_caller_of_the_reusable_workflow_is_accounted_for(self):
        callers = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for name, job in load(path.name).get("jobs", {}).items():
                if job.get("uses") == "./.github/workflows/_compose-boot-test.yml":
                    callers.append((path.name, name))
        assert callers == [("boot-test-all.yml", "compose-boot-test-all"), ("pr-checks.yml", "compose-boot-test")]
