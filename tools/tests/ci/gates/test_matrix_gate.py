"""Tests for ci.gates.matrix_gate.

`evaluate` runs on hand-built `needs` contexts; the CLI reads the same JSON
from the environment; and a class of invariants parses the real workflow, so
the gate's two lists (the `needs:` of the job and the MATRIX_JOBS it is
given) can't drift from the jobs that actually use a matrix.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ci.gates import matrix_gate as mg

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = REPO_ROOT / ".github/workflows"
MATRIX = ["molecule", "compose-boot-test"]


def needs(**results: str) -> dict[str, dict[str, object]]:
    return {name.replace("_", "-"): {"result": result, "outputs": {}} for name, result in results.items()}


ALL_GOOD = {"detect_changes": "success", "warm_uv_cache": "success", "molecule": "success", "compose_boot_test": "success"}


class EvaluateTests(unittest.TestCase):
    def errors(self, **overrides: str) -> list[str]:
        return mg.evaluate(needs(**{**ALL_GOOD, **overrides}), MATRIX)

    def test_everything_succeeding_passes(self):
        self.assertEqual(self.errors(), [])

    def test_skipped_matrix_jobs_pass(self):
        self.assertEqual(self.errors(molecule="skipped", compose_boot_test="skipped"), [])

    def test_a_failed_or_cancelled_matrix_job_fails(self):
        for result in ("failure", "cancelled"):
            with self.subTest(result=result):
                self.assertEqual(self.errors(molecule=result), [f"A required job did not pass (molecule: {result})"])

    def test_an_upstream_job_must_be_exactly_success(self):
        for result in ("failure", "cancelled", "skipped"):
            with self.subTest(result=result):
                self.assertEqual(self.errors(warm_uv_cache=result), [f"An upstream job did not succeed (warm-uv-cache: {result})"])

    def test_upstream_failure_fails_even_though_the_matrix_jobs_report_skipped(self):
        errors = self.errors(detect_changes="failure", molecule="skipped", compose_boot_test="skipped")
        self.assertEqual(errors, ["An upstream job did not succeed (detect-changes: failure)"])

    def test_an_unrecognised_result_never_counts_as_a_pass(self):
        self.assertEqual(len(self.errors(molecule="mystery")), 1)
        self.assertEqual(len(self.errors(detect_changes="mystery")), 1)
        self.assertEqual(len(mg.evaluate({"molecule": {}}, ["molecule"])), 1)

    def test_every_failing_job_is_reported_not_just_the_first(self):
        errors = self.errors(detect_changes="failure", molecule="failure", compose_boot_test="cancelled")
        self.assertEqual(len(errors), 3)

    def test_a_matrix_job_that_is_not_in_needs_is_an_error(self):
        errors = mg.evaluate(needs(detect_changes="success"), ["molecule"])
        self.assertEqual(errors, ["molecule is named as a matrix job but is not in `needs`"])

    def test_a_job_in_needs_but_not_named_a_matrix_job_is_held_to_success(self):
        self.assertEqual(len(mg.evaluate(needs(detect_changes="success", extra="skipped"), [])), 1)


class CliTests(unittest.TestCase):
    def run_main(self, env: dict[str, str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        clean = {k: v for k, v in os.environ.items() if k not in ("NEEDS", "MATRIX_JOBS")}
        with patch.dict(os.environ, {**clean, **env}, clear=True), redirect_stdout(out), redirect_stderr(err):
            code = mg.main()
        return code, out.getvalue(), err.getvalue()

    def test_passes_and_reports_every_result(self):
        code, out, _ = self.run_main({"NEEDS": json.dumps(needs(**ALL_GOOD)), "MATRIX_JOBS": "molecule compose-boot-test"})
        self.assertEqual(code, 0)
        self.assertIn("molecule=success", out)

    def test_fails_with_an_error_annotation_per_failing_job(self):
        code, out, _ = self.run_main({"NEEDS": json.dumps(needs(**{**ALL_GOOD, "molecule": "failure"})), "MATRIX_JOBS": "molecule compose-boot-test"})
        self.assertEqual(code, 1)
        self.assertIn("::error::A required job did not pass (molecule: failure)", out)

    def test_matrix_jobs_are_split_on_any_whitespace(self):
        code, _, _ = self.run_main({"NEEDS": json.dumps(needs(**ALL_GOOD)), "MATRIX_JOBS": "molecule\ncompose-boot-test\n"})
        self.assertEqual(code, 0)

    def test_missing_or_malformed_needs_fails_closed(self):
        for value in (None, "", "not json", "[]", "{}", '{"a": "success"}'):
            env = {"MATRIX_JOBS": "molecule"} | ({} if value is None else {"NEEDS": value})
            with self.subTest(needs=value):
                self.assertEqual(self.run_main(env)[0], 1)

    def test_a_missing_matrix_jobs_variable_means_every_job_is_held_to_success(self):
        code, out, _ = self.run_main({"NEEDS": json.dumps(needs(**{**ALL_GOOD, "molecule": "skipped"}))})
        self.assertEqual(code, 1)
        self.assertIn("molecule: skipped", out)


def _job_uses_a_matrix(job: dict[str, object]) -> bool:
    strategy = job.get("strategy")
    if isinstance(strategy, dict) and "matrix" in strategy:
        return True
    uses = job.get("uses")
    if isinstance(uses, str) and uses.startswith("./.github/workflows/"):
        called = yaml.safe_load((REPO_ROOT / uses.removeprefix("./")).read_text())
        return any(_job_uses_a_matrix(inner) for inner in called["jobs"].values())
    return False


class RealWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load((WORKFLOWS / "pr-checks.yml").read_text())
        cls.gate = cls.workflow["jobs"]["matrix-jobs-gate"]
        cls.step = next(step for step in cls.gate["steps"] if "matrix_gate" in step.get("run", ""))

    def test_the_gate_lists_every_job_that_uses_a_matrix(self):
        matrix_jobs = {name for name, job in self.workflow["jobs"].items() if _job_uses_a_matrix(job)}
        self.assertTrue(matrix_jobs)
        self.assertLessEqual(matrix_jobs, set(self.gate["needs"]))

    def test_matrix_jobs_env_is_exactly_the_jobs_that_use_a_matrix(self):
        matrix_jobs = {name for name, job in self.workflow["jobs"].items() if _job_uses_a_matrix(job)}
        self.assertEqual(set(self.step["env"]["MATRIX_JOBS"].split()), matrix_jobs)

    def test_every_other_needed_job_is_one_that_always_runs_and_must_succeed(self):
        matrix_jobs = set(self.step["env"]["MATRIX_JOBS"].split())
        upstream = set(self.gate["needs"]) - matrix_jobs
        self.assertEqual(upstream, {"detect-changes", "warm-uv-cache", "warm-galaxy-cache"})
        for name in upstream:
            with self.subTest(job=name):
                self.assertNotIn("if", self.workflow["jobs"][name])

    def test_the_gate_runs_even_when_its_needs_are_skipped_or_failed(self):
        self.assertEqual(self.gate["if"], "always()")

    def test_the_step_hands_the_whole_needs_context_to_the_module(self):
        self.assertEqual(self.step["env"]["NEEDS"], "${{ toJSON(needs) }}")
        self.assertEqual(self.step["run"], "python3 -m ci.gates.matrix_gate")
        self.assertEqual(self.step["working-directory"], "tools")

    def test_the_gate_checks_out_only_what_it_runs(self):
        checkout = next(step for step in self.gate["steps"] if step.get("uses", "").startswith("actions/checkout"))
        self.assertEqual(checkout["with"]["sparse-checkout"], "tools/ci")


if __name__ == "__main__":
    unittest.main()
