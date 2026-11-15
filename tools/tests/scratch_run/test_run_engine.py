from __future__ import annotations

import json
import tarfile

import pytest
from scratch_run.engine import EXIT_NOT_RUN, EXIT_OK, EXIT_STEP_FAILED, judge, run
from scratch_run.spec import Step, parse_spec
from scratch_run_fakes import FakeBackend

APPLY = Step("s", "play", "apply", "ok")
CHECK_UNCHANGED = Step("s", "play", "check", "unchanged")
CHECK_CHANGED = Step("s", "play", "check", "changed")
FLOWS_PASS = Step("s", "flows", "", "pass", tags=("services",))
FLOWS_FAIL = Step("s", "flows", "", "fail", flow_ids=("services-gateway-dns",))
BLOCK = Step("s", "block", "present", "")
VLANS = Step("s", "vlans", "check", "")
VM = Step("s", "vm", "up", "")
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
        pytest.param(FLOWS_FAIL, 1, "FAIL services-gateway-dns: blocked\n", True, id="flows-fail-as-wanted"),
        pytest.param(FLOWS_FAIL, 1, "Traceback: the runner crashed\n", False, id="a-crash-is-not-the-failure-wanted"),
        pytest.param(FLOWS_FAIL, 0, "", False, id="flows-pass-when-a-failure-was-wanted"),
        pytest.param(FLOWS_FAIL, 2, "", False, id="nothing-selected-is-not-a-failure"),
        pytest.param(BLOCK, 0, "", True, id="block-ok"),
        pytest.param(BLOCK, 4, "", False, id="block-fails"),
        pytest.param(VLANS, 0, "the gateway has 6 VLAN interfaces\n", True, id="vlans-match"),
        pytest.param(VLANS, 1, "the gateway has 5 VLAN interfaces\n", False, id="vlans-differ"),
        pytest.param(VM, 0, "VM 208 answered over ssh\n", True, id="vm-answers"),
        pytest.param(VM, 1, "VM 208 did not answer\n", False, id="vm-does-not-answer"),
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
    assert (status, backend.calls) == (EXIT_STEP_FAILED, ["preflight", "up", "logs", "down"])


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


def test_a_run_says_what_it_is_doing_before_each_step_and_how_long_each_took(rehearsal, tmp_path):
    lines: list[str] = []
    ticks = iter(range(0, 10_000, 7))
    run(rehearsal, FakeBackend(), tmp_path, "T8", lambda: float(next(ticks)), say=lines.append)
    assert lines[0] == "STEP up: building the gateway (its log follows; this takes minutes)"
    assert "STEP play-apply: running (play apply)" in lines
    assert "STEP dns-blocked: running (flows services-gateway-dns)" in lines
    assert "STEP down: removing the gateway" in lines
    assert any(line.startswith("STEP up: PASS") and line.endswith("; 7s)") for line in lines)


def test_the_run_ends_with_each_steps_time_and_the_total(rehearsal, tmp_path):
    lines: list[str] = []
    ticks = iter(range(0, 10_000, 7))
    run(rehearsal, FakeBackend(), tmp_path, "T9", lambda: float(next(ticks)), say=lines.append)
    table = next(line for line in lines if line.startswith("  PASS up"))
    assert "PASS up" in table and "PASS dns-restored" in table and "PASS down" in table
    assert f"  total {7 * len(rehearsal.steps) + 14}s" in lines


def test_a_vlans_step_says_what_the_check_found_in_the_last_line_of_its_output():
    assert judge(VLANS, 1, "GET /x -> HTTP 200\n{}\nthe gateway has 5 VLAN interfaces; the spec seeds 6\n\n") == (
        False,
        "the gateway has 5 VLAN interfaces; the spec seeds 6",
    )
    assert judge(VLANS, 1, "") == (False, "the check exited 1")


def test_the_build_logs_are_kept_in_the_results_and_scanned_like_the_rest(rehearsal, tmp_path):
    backend = FakeBackend(log_files={"build-seed.txt": "seed built\n", "update-job-update.log": "job ran\n"})
    assert run(rehearsal, backend, tmp_path, "T10", lambda: 0.0, say=lambda line: None) == EXIT_OK
    kept = tmp_path / "rehearsal-T10" / "logs"
    assert {path.name: path.read_text() for path in kept.iterdir()} == {"build-seed.txt": "seed built\n", "update-job-update.log": "job ran\n"}
    with tarfile.open(tmp_path / "results-rehearsal-T10.tgz") as tar:
        assert "rehearsal-T10/logs/build-seed.txt" in tar.getnames()


def test_the_logs_are_taken_before_the_gateway_is_removed_even_when_the_build_failed(rehearsal, tmp_path):
    backend = FakeBackend(answers={"up": (1, "tofu apply failed\n")}, log_files={"apply.txt": "Error: VM create\n"})
    run(rehearsal, backend, tmp_path, "T11", lambda: 0.0, say=lambda line: None)
    assert backend.calls == ["preflight", "up", "logs", "down"]
    assert (tmp_path / "rehearsal-T11" / "logs" / "apply.txt").read_text() == "Error: VM create\n"


def test_a_run_with_no_logs_has_no_logs_directory(rehearsal, tmp_path):
    run(rehearsal, FakeBackend(), tmp_path, "T12", lambda: 0.0, say=lambda line: None)
    assert not (tmp_path / "rehearsal-T12" / "logs").exists()


def test_a_log_name_cannot_put_a_file_outside_the_logs_directory(rehearsal, tmp_path):
    backend = FakeBackend(log_files={"../../escaped.txt": "x\n"})
    run(rehearsal, backend, tmp_path, "T13", lambda: 0.0, say=lambda line: None)
    assert (tmp_path / "rehearsal-T13" / "logs" / "escaped.txt").is_file()
    assert not (tmp_path / "escaped.txt").exists()


def test_a_credential_value_in_a_kept_log_fails_the_run_and_no_archive_is_written(rehearsal, tmp_path):
    backend = FakeBackend(log_files={"apply.txt": "the key was s3cret-key-value\n"}, secret_values=["s3cret-key-value"])
    lines: list[str] = []
    assert run(rehearsal, backend, tmp_path, "T14", lambda: 0.0, say=lines.append) == EXIT_STEP_FAILED
    assert "A CREDENTIAL VALUE IS IN: apply.txt; no archive was written" in lines


def test_a_vm_step_is_run_by_the_backend_and_says_what_happened_in_its_last_line(tmp_path):
    spec = parse_spec(
        {
            "name": "canary-vm",
            "description": "d",
            "canary_vm": {"zone": "services"},
            "steps": [{"id": "vm-up", "vm": "up"}, {"id": "flows", "flows": {"tags": ["services"]}}],
        }
    )
    backend = FakeBackend(answers={"vm": (0, "tofu applied\nVM 208 answered over ssh after 40s\n")})
    lines: list[str] = []
    assert run(spec, backend, tmp_path, "T20", lambda: 0.0, say=lines.append) == EXIT_OK
    assert backend.calls == ["preflight", "up", "vm", "flows:services", "logs", "down"]
    assert "STEP vm-up: running (vm up)" in lines
    assert "STEP vm-up: PASS (VM 208 answered over ssh after 40s; 0s)" in lines
