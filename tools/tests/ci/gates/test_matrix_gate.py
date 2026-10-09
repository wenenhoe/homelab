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
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
import yaml
from ci.gates import matrix_gate as mg

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = REPO_ROOT / ".github/workflows"
MATRIX = ["molecule", "compose-boot-test"]


def needs(**results: str) -> dict[str, dict[str, object]]:
    return {name.replace("_", "-"): {"result": result, "outputs": {}} for name, result in results.items()}


ALL_GOOD = {"detect_changes": "success", "warm_uv_cache": "success", "molecule": "success", "compose_boot_test": "success"}


def errors(**overrides: str) -> list[str]:
    return mg.evaluate(needs(**{**ALL_GOOD, **overrides}), MATRIX)


class TestEvaluate:
    def test_everything_succeeding_passes(self):
        assert errors() == []

    def test_skipped_matrix_jobs_pass(self):
        assert errors(molecule="skipped", compose_boot_test="skipped") == []

    @pytest.mark.parametrize("result", ["failure", "cancelled"])
    def test_a_failed_or_cancelled_matrix_job_fails(self, result):
        assert errors(molecule=result) == [f"A required job did not pass (molecule: {result})"]

    @pytest.mark.parametrize("result", ["failure", "cancelled", "skipped"])
    def test_an_upstream_job_must_be_exactly_success(self, result):
        assert errors(warm_uv_cache=result) == [f"An upstream job did not succeed (warm-uv-cache: {result})"]

    def test_upstream_failure_fails_even_though_the_matrix_jobs_report_skipped(self):
        found = errors(detect_changes="failure", molecule="skipped", compose_boot_test="skipped")
        assert found == ["An upstream job did not succeed (detect-changes: failure)"]

    def test_an_unrecognised_result_never_counts_as_a_pass(self):
        assert len(errors(molecule="mystery")) == 1
        assert len(errors(detect_changes="mystery")) == 1
        assert len(mg.evaluate({"molecule": {}}, ["molecule"])) == 1

    def test_every_failing_job_is_reported_not_just_the_first(self):
        found = errors(detect_changes="failure", molecule="failure", compose_boot_test="cancelled")
        assert len(found) == 3

    def test_a_matrix_job_that_is_not_in_needs_is_an_error(self):
        found = mg.evaluate(needs(detect_changes="success"), ["molecule"])
        assert found == ["molecule is named as a matrix job but is not in `needs`"]

    def test_a_job_in_needs_but_not_named_a_matrix_job_is_held_to_success(self):
        assert len(mg.evaluate(needs(detect_changes="success", extra="skipped"), [])) == 1


@pytest.fixture
def run_main(monkeypatch):
    def run(env: dict[str, str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        for name in ("NEEDS", "MATRIX_JOBS"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        with redirect_stdout(out), redirect_stderr(err):
            code = mg.main()
        return code, out.getvalue(), err.getvalue()

    return run


class TestCli:
    def test_passes_and_reports_every_result(self, run_main):
        code, out, _ = run_main({"NEEDS": json.dumps(needs(**ALL_GOOD)), "MATRIX_JOBS": "molecule compose-boot-test"})
        assert code == 0
        assert "molecule=success" in out

    def test_fails_with_an_error_annotation_per_failing_job(self, run_main):
        code, out, _ = run_main({"NEEDS": json.dumps(needs(**{**ALL_GOOD, "molecule": "failure"})), "MATRIX_JOBS": "molecule compose-boot-test"})
        assert code == 1
        assert "::error::A required job did not pass (molecule: failure)" in out

    def test_matrix_jobs_are_split_on_any_whitespace(self, run_main):
        code, _, _ = run_main({"NEEDS": json.dumps(needs(**ALL_GOOD)), "MATRIX_JOBS": "molecule\ncompose-boot-test\n"})
        assert code == 0

    # NEEDS is the workflow's `toJSON(needs)` (pr-checks.yml): unset if the step loses its env, any other shape if the expression is edited.
    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(None, id="unset"),
            pytest.param("", id="empty"),
            pytest.param("not json", id="not-json"),
            pytest.param("[]", id="empty-list"),
            pytest.param("{}", id="empty-object"),
            pytest.param('{"a": "success"}', id="entry-is-not-an-object"),
        ],
    )
    def test_missing_or_malformed_needs_fails_closed(self, run_main, value):
        env = {"MATRIX_JOBS": "molecule"} | ({} if value is None else {"NEEDS": value})
        assert run_main(env)[0] == 1

    def test_a_missing_matrix_jobs_variable_means_every_job_is_held_to_success(self, run_main):
        code, out, _ = run_main({"NEEDS": json.dumps(needs(**{**ALL_GOOD, "molecule": "skipped"}))})
        assert code == 1
        assert "molecule: skipped" in out


def _job_uses_a_matrix(job: dict[str, object]) -> bool:
    strategy = job.get("strategy")
    if isinstance(strategy, dict) and "matrix" in strategy:
        return True
    uses = job.get("uses")
    if isinstance(uses, str) and uses.startswith("./.github/workflows/"):
        called = yaml.safe_load((REPO_ROOT / uses.removeprefix("./")).read_text())
        return any(_job_uses_a_matrix(inner) for inner in called["jobs"].values())
    return False


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load((WORKFLOWS / "pr-checks.yml").read_text())


@pytest.fixture(scope="module")
def gate(workflow):
    return workflow["jobs"]["matrix-jobs-gate"]


@pytest.fixture(scope="module")
def step(gate):
    return next(step for step in gate["steps"] if "matrix_gate" in step.get("run", ""))


class TestRealWorkflow:
    def test_the_gate_lists_every_job_that_uses_a_matrix(self, workflow, gate):
        matrix_jobs = {name for name, job in workflow["jobs"].items() if _job_uses_a_matrix(job)}
        assert matrix_jobs
        assert matrix_jobs <= set(gate["needs"])

    def test_matrix_jobs_env_is_exactly_the_jobs_that_use_a_matrix(self, workflow, step):
        matrix_jobs = {name for name, job in workflow["jobs"].items() if _job_uses_a_matrix(job)}
        assert set(step["env"]["MATRIX_JOBS"].split()) == matrix_jobs

    def test_every_other_needed_job_is_one_that_always_runs_and_must_succeed(self, workflow, gate, step, subtests):
        matrix_jobs = set(step["env"]["MATRIX_JOBS"].split())
        upstream = set(gate["needs"]) - matrix_jobs
        assert upstream == {"detect-changes", "warm-uv-cache", "warm-galaxy-cache", "molecule-coverage"}
        for name in upstream:
            with subtests.test(job=name):
                assert workflow["jobs"][name].get("if", "always()") == "always()"

    def test_molecule_coverage_runs_every_time_so_the_gate_can_require_its_success(self, workflow):
        """Skipped when nothing was tested would fail the gate, so it always runs and its steps decide."""
        job = workflow["jobs"]["molecule-coverage"]
        assert job["if"] == "always()"
        assert all(step.get("if") == "needs.detect-changes.outputs.roles != '[]'" for step in job["steps"])

    def test_the_gate_runs_even_when_its_needs_are_skipped_or_failed(self, gate):
        assert gate["if"] == "always()"

    def test_the_step_hands_the_whole_needs_context_to_the_module(self, step):
        assert step["env"]["NEEDS"] == "${{ toJSON(needs) }}"
        assert step["run"] == "python3 -m ci.gates.matrix_gate"
        assert step["working-directory"] == "tools"

    def test_the_gate_checks_out_only_what_it_runs(self, gate):
        checkout = next(step for step in gate["steps"] if step.get("uses", "").startswith("actions/checkout"))
        assert checkout["with"]["sparse-checkout"] == "tools/ci"
