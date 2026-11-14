from __future__ import annotations

import tarfile

import pytest
from conftest import RUNS, FakeBackend
from scratch_run.__main__ import main

SPEC = str(RUNS / "rehearsal.yaml")


def factory(backend):
    return lambda out, url, checksum, env: backend


def test_check_spec_reads_the_spec_and_needs_nothing_else(capsys):
    assert main([SPEC, "--check-spec"]) == 0
    assert capsys.readouterr().out == "rehearsal: 9 steps, valid\n"


def test_a_bad_spec_exits_2_and_names_the_problems(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: Bad\n")
    assert main([str(bad), "--check-spec"]) == 2
    assert "`name` must be lowercase" in capsys.readouterr().err


def test_a_run_needs_an_out_dir(capsys):
    with pytest.raises(SystemExit) as stop:
        main([SPEC])
    assert stop.value.code == 2
    assert "OUT_DIR is required" in capsys.readouterr().err


def test_preflight_lists_the_problems_and_runs_nothing(tmp_path, capsys):
    backend = FakeBackend(problems=["NODE is not set"])
    assert main([SPEC, str(tmp_path / "out"), "--preflight"], backend_factory=factory(backend)) == 2
    assert capsys.readouterr().out == "- NODE is not set\n"
    assert backend.calls == ["preflight"]


def test_preflight_with_nothing_missing_says_the_run_is_ready(tmp_path, capsys):
    assert main([SPEC, str(tmp_path / "out"), "--preflight"], backend_factory=factory(FakeBackend())) == 0
    assert capsys.readouterr().out == "rehearsal: ready to run\n"


def test_a_run_bundles_its_results_in_the_out_dir(tmp_path, capsys):
    backend = FakeBackend()
    assert main([SPEC, str(tmp_path / "out"), "--keep"], backend_factory=factory(backend)) == 0
    archives = list((tmp_path / "out").glob("results-rehearsal-*.tgz"))
    assert len(archives) == 1 and "down" not in backend.calls
    with tarfile.open(archives[0]) as tar:
        assert any(name.endswith("/results.md") for name in tar.getnames())
    assert "ALL STEPS PASSED" in capsys.readouterr().out
