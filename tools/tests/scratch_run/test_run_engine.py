from __future__ import annotations

import json
import tarfile

import pytest
from conftest import FakeBackend
from scratch_run.engine import EXIT_NOT_RUN, EXIT_OK, EXIT_STEP_FAILED, judge, run
from scratch_run.spec import Step

APPLY = Step("s", "play", "apply", "ok")
CHECK_UNCHANGED = Step("s", "play", "check", "unchanged")
CHECK_CHANGED = Step("s", "play", "check", "changed")
FLOWS_PASS = Step("s", "flows", "", "pass", tags=("services",))
FLOWS_FAIL = Step("s", "flows", "", "fail", flow_ids=("services-gateway-dns",))
BLOCK = Step("s", "block", "present", "")
RECAP = "localhost                  : ok=9    changed={n}    unreachable=0    failed=0\n"


@pytest.mark.parametrize(
    ("step", "status", "output", "passed"),
    [
        pytest.param(APPLY, 0, "", True, id="apply-ok"),
        pytest.param(APPLY, 2, "", False, id="apply-fails"),
        pytest.param(CHECK_UNCHANGED, 0, RECAP.format(n=0), True, id="unchanged-when-recap-says-0"),
        pytest.param(CHECK_UNCHANGED, 0, RECAP.format(n=3), False, id="unchanged-but-recap-says-3"),
        pytest.param(CHECK_UNCHANGED, 0, "no recap here\n", False, id="unchanged-without-recap"),
        pytest.param(CHECK_UNCHANGED, 2, RECAP.format(n=0), False, id="unchanged-but-the-play-failed"),
        pytest.param(CHECK_CHANGED, 0, RECAP.format(n=3), True, id="changed-when-recap-says-3"),
        pytest.param(CHECK_CHANGED, 0, RECAP.format(n=0), False, id="changed-but-recap-says-0"),
        pytest.param(FLOWS_PASS, 0, "", True, id="flows-pass"),
        pytest.param(FLOWS_PASS, 1, "", False, id="flows-fail-unexpectedly"),
        pytest.param(FLOWS_FAIL, 1, "", True, id="flows-fail-as-wanted"),
        pytest.param(FLOWS_FAIL, 0, "", False, id="flows-pass-when-a-failure-was-wanted"),
        pytest.param(FLOWS_FAIL, 2, "", False, id="nothing-selected-is-not-a-failure"),
        pytest.param(BLOCK, 0, "", True, id="block-ok"),
        pytest.param(BLOCK, 4, "", False, id="block-fails"),
    ],
)
def test_a_step_passes_only_with_the_outcome_the_spec_expects(step, status, output, passed):
    assert judge(step, status, output)[0] is passed


def test_a_run_where_every_step_passes_writes_one_file_per_step_and_an_archive(rehearsal, tmp_path):
    backend = FakeBackend()
    lines: list[str] = []
    status = run(rehearsal, backend, tmp_path, "T1", iter(range(0, 1000, 3)).__next__, say=lines.append)
    results = tmp_path / "rehearsal-T1"
    assert status == EXIT_OK
    assert backend.calls[0:2] == ["preflight", "up"] and backend.calls[-1] == "down"
    assert sorted(path.stem for path in results.glob("*.txt")) == sorted(["up", "down", *(step.id for step in rehearsal.steps)])
    assert all(entry["passed"] for entry in json.loads((results / "results.json").read_text()))
    with tarfile.open(tmp_path / "results-rehearsal-T1.tgz") as tar:
        assert "rehearsal-T1/results.md" in tar.getnames()
    assert lines[-2] == "ALL STEPS PASSED"


def test_a_step_with_the_wrong_outcome_fails_the_run_but_the_rest_still_run_and_the_gateway_is_removed(rehearsal, tmp_path):
    backend = FakeBackend(answers={"flows:desktops": (1, "a flow failed\n")})
    lines: list[str] = []
    status = run(rehearsal, backend, tmp_path, "T2", lambda: 0.0, say=lines.append)
    assert status == EXIT_STEP_FAILED
    assert "block:absent" in backend.calls and backend.calls[-1] == "down"
    assert "1 STEP(S) FAILED: desktops-flows" in lines


def test_a_gateway_that_does_not_come_up_skips_the_steps_but_is_still_removed(rehearsal, tmp_path):
    backend = FakeBackend(answers={"up": (1, "tofu apply failed\n")})
    status = run(rehearsal, backend, tmp_path, "T3", lambda: 0.0, say=lambda line: None)
    assert (status, backend.calls) == (EXIT_STEP_FAILED, ["preflight", "up", "down"])


def test_a_missing_precondition_stops_the_run_before_anything_is_built_and_names_each(rehearsal, tmp_path):
    backend = FakeBackend(problems=["NODE is not set", "ssh is not installed here"])
    lines: list[str] = []
    status = run(rehearsal, backend, tmp_path, "T4", lambda: 0.0, say=lines.append)
    assert (status, backend.calls) == (EXIT_NOT_RUN, ["preflight"])
    assert lines[1:] == ["  - NODE is not set", "  - ssh is not installed here"]
    assert list(tmp_path.iterdir()) == []


def test_keep_leaves_the_gateway_up(rehearsal, tmp_path):
    backend = FakeBackend()
    status = run(rehearsal, backend, tmp_path, "T5", lambda: 0.0, keep=True, say=lambda line: None)
    assert status == EXIT_OK
    assert "down" not in backend.calls


def test_a_credential_value_in_a_result_fails_the_run_and_no_archive_is_written(rehearsal, tmp_path):
    backend = FakeBackend(answers={"flows:services": (0, "the key was s3cret-key-value\n")}, secret_values=["s3cret-key-value", "short"])
    lines: list[str] = []
    status = run(rehearsal, backend, tmp_path, "T6", lambda: 0.0, say=lines.append)
    assert status == EXIT_STEP_FAILED
    assert "A CREDENTIAL VALUE IS IN: services-flows.txt; no archive was written" in lines
    assert not list(tmp_path.glob("*.tgz"))


def test_a_value_shorter_than_eight_characters_is_not_searched_for(rehearsal, tmp_path):
    backend = FakeBackend(answers={"flows:services": (0, "a short word\n")}, secret_values=["short"])
    assert run(rehearsal, backend, tmp_path, "T7", lambda: 0.0, say=lambda line: None) == EXIT_OK
