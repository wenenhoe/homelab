"""The live block: what it writes to a terminal, and that it writes nothing anywhere else."""

from __future__ import annotations

import io

import pytest
from land_series.live import MAX_LISTED_CHECKS, LiveBlock, check_lines


class Terminal(io.StringIO):
    """A stream that reports being a terminal."""

    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def ordinary_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")


def test_each_draw_moves_up_over_the_last_one_and_clears_it_before_writing() -> None:
    stream = Terminal()
    block = LiveBlock(stream, columns=lambda: 80)

    block.show(["one", "two"])
    block.show(["three"])
    block.show([])

    assert stream.getvalue() == "one\ntwo\n" + "\x1b[2A\x1b[J" + "three\n" + "\x1b[1A\x1b[J"


def test_nothing_is_moved_back_over_when_nothing_was_drawn() -> None:
    stream = Terminal()

    LiveBlock(stream, columns=lambda: 80).show([])

    assert stream.getvalue() == ""


def test_a_line_wider_than_the_terminal_is_cut_so_it_cannot_wrap_into_a_second_row() -> None:
    stream = Terminal()

    LiveBlock(stream, columns=lambda: 10).show(["abcdefghijklmnop"])

    assert stream.getvalue() == "abcdefghi\n"


def test_a_stream_that_is_not_a_terminal_receives_nothing() -> None:
    stream = io.StringIO()

    block = LiveBlock(stream, columns=lambda: 80)
    block.show(["one"])
    block.show([])

    assert stream.getvalue() == ""


def test_a_dumb_terminal_receives_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "dumb")
    stream = Terminal()

    LiveBlock(stream, columns=lambda: 80).show(["one"])

    assert stream.getvalue() == ""


def test_the_check_block_counts_the_passed_and_lists_the_rest_by_whether_they_have_started() -> None:
    buckets = {"lint": {"pass"}, "docs": {"skipping"}, "tests": {"pending"}}

    lines = check_lines("pull request 0001", ["docs", "gate", "lint", "tests"], buckets)

    assert lines == ["pull request 0001: 2/4 required checks passed", "  gate  (not reported yet)", "  tests  (running)"]


def test_a_long_list_of_checks_still_to_pass_is_cut_with_a_count_of_the_rest() -> None:
    names = [f"check-{number:02}" for number in range(MAX_LISTED_CHECKS + 3)]

    lines = check_lines("pull request 0001", names, {})

    assert lines[0] == "pull request 0001: 0/11 required checks passed"
    assert lines[1:-1] == [f"  {name}  (not reported yet)" for name in names[:MAX_LISTED_CHECKS]]
    assert lines[-1] == "  and 3 more"
