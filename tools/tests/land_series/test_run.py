"""Starting a program: what comes back, and the three ways it can go wrong."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from land_series.run import CommandFailed, TimedOut, ToolMissing, checked, run

PYTHON = sys.executable


def test_the_exit_code_and_both_streams_come_back_for_the_caller_to_read() -> None:
    result = run([PYTHON, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"])

    assert (result.returncode, result.text, result.output) == (3, "out", "out\nerr")


def test_stdin_is_passed_on_and_is_empty_when_there_is_none() -> None:
    echo = [PYTHON, "-c", "import sys; print(repr(sys.stdin.read()))"]

    assert run(echo, stdin=b"asked").text == "'asked'"
    assert run(echo).text == "''"


def test_env_adds_to_the_environment_and_cwd_sets_the_directory(tmp_path: Path) -> None:
    result = run([PYTHON, "-c", "import os; print(os.environ['LAND_X'], os.getcwd())"], env={"LAND_X": "set"}, cwd=tmp_path)

    assert result.text == f"set {tmp_path.resolve()}"


def test_a_program_that_is_not_installed_is_named() -> None:
    with pytest.raises(ToolMissing, match="`land-series-no-such-tool` is not installed or is not on PATH"):
        run(["land-series-no-such-tool", "--version"])


def test_a_program_that_runs_past_its_time_is_stopped_and_named() -> None:
    with pytest.raises(TimedOut, match=r"did not finish within 0\.2 seconds"):
        run([PYTHON, "-c", "import time; time.sleep(30)"], timeout=0.2)


def test_a_failed_command_keeps_what_a_caller_needs_to_decide_on_it() -> None:
    with pytest.raises(CommandFailed) as raised:
        checked([PYTHON, "-c", "import sys; print('no way', file=sys.stderr); sys.exit(4)"])

    assert (raised.value.returncode, raised.value.output, raised.value.argv[0]) == (4, "no way", PYTHON)


def test_a_command_that_succeeds_is_returned() -> None:
    assert checked([PYTHON, "-c", "print('fine')"]).text == "fine"
