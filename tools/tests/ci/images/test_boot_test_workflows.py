"""How the two callers of the reusable boot-test workflow differ (ADR 0064 layout, docs/ci.md#dockerfile-changes).

A PR boots the Dockerfile it changed, because that image isn't published until
after merge. A full sweep boots the published images instead, so it also
fails when a compose pin's tag was never pushed. The switch is one input.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[4] / ".github/workflows"


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


class BootTestWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reusable = load("_compose-boot-test.yml")
        cls.inputs = cls.reusable[True]["workflow_call"]["inputs"]  # PyYAML reads the bare key `on` as True
        cls.steps = cls.reusable["jobs"]["compose-boot-test"]["steps"]

    def test_the_input_is_an_optional_boolean_that_defaults_on(self):
        spec = self.inputs["build-dockerfiles"]
        self.assertEqual(spec["type"], "boolean")
        self.assertIs(spec["default"], True)
        self.assertFalse(spec["required"])

    def test_only_the_dockerfile_build_step_is_gated_on_it(self):
        gated = [step["name"] for step in self.steps if step.get("if") == "inputs.build-dockerfiles"]
        self.assertEqual(len(gated), 1)
        self.assertIn("Dockerfile", gated[0])
        step = next(step for step in self.steps if step.get("if") == "inputs.build-dockerfiles")
        self.assertIn("ci.images.build shadow-tag", step["run"])

    def test_a_pr_takes_the_default_and_builds_its_dockerfiles(self):
        job = load("pr-checks.yml")["jobs"]["compose-boot-test"]
        self.assertNotIn("build-dockerfiles", job["with"])

    def test_the_full_sweep_boots_the_published_images(self):
        job = load("boot-test-all.yml")["jobs"]["compose-boot-test-all"]
        self.assertIs(job["with"]["build-dockerfiles"], False)

    def test_the_full_sweep_stays_manual_only(self):
        triggers = load("boot-test-all.yml")[True]
        self.assertEqual(set(triggers), {"workflow_dispatch"})

    def test_every_caller_of_the_reusable_workflow_is_accounted_for(self):
        callers = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for name, job in load(path.name).get("jobs", {}).items():
                if job.get("uses") == "./.github/workflows/_compose-boot-test.yml":
                    callers.append((path.name, name))
        self.assertEqual(callers, [("boot-test-all.yml", "compose-boot-test-all"), ("pr-checks.yml", "compose-boot-test")])


if __name__ == "__main__":
    unittest.main()
