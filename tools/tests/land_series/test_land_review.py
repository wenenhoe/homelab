"""The review of the commits on the stop list: the summary, the diff in a pager and the one prompt."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator

import pytest
from land_series import review
from land_series.manifest import Layer
from land_series.review import Change, Stop, ask, page, summary, visible


def stop(layer_id: str = "0001a", subject: str = "chore: change a tool", paths: tuple[str, ...] = ("tools/run.py",), diff: str = "+print()\n") -> Stop:
    layer = Layer(layer_id, "slug", b"", subject, 0, "series")
    return Stop(layer, tuple(Change(path, 1, 0) for path in paths), diff)


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setenv("TERM", "xterm")


def answers(monkeypatch: pytest.MonkeyPatch, *replies: str) -> list[str]:
    """Reply to each prompt in turn, then end the input; return the prompts that were shown."""
    prompts: list[str] = []
    queued: Iterator[str] = iter(replies)

    def reply(prompt: str) -> str:
        prompts.append(prompt)
        try:
            return next(queued)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", reply)
    return prompts


def test_the_summary_groups_each_commits_files_by_what_runs_them() -> None:
    paths = ("tools/run.py", "tools/tests/test_run.py", ".github/workflows/ci.yml", "uv.lock", ".config/zizmor.yml")

    assert summary([stop(paths=paths)])[1:] == [
        "",
        "0001a  chore: change a tool",
        "  hooks, configuration and dependencies",
        "    +1 -0  uv.lock",
        "    +1 -0  .config/zizmor.yml",
        "  CI workflows and actions",
        "    +1 -0  .github/workflows/ci.yml",
        "  tool tests",
        "    +1 -0  tools/tests/test_run.py",
        "  tools code",
        "    +1 -0  tools/run.py",
    ]


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        pytest.param("a\x1b[8mhidden", "a\\x1b[8mhidden", id="a terminal escape"),
        pytest.param("run()\rpass", "run()\\rpass", id="a carriage return"),
        pytest.param("if x‮:", "if x\\u202e:", id="a direction override"),
        pytest.param("name\udcff", "name\\udcff", id="a byte that is not UTF-8 in a file name"),
        pytest.param("\ta é\n", "\ta é\n", id="tabs, newlines and accents stay"),
    ],
)
def test_control_and_format_characters_are_written_out(text: str, shown: str) -> None:
    assert visible(text) == shown


def test_nothing_in_a_subject_or_a_file_name_reaches_the_terminal_as_control_characters() -> None:
    lines = summary([stop(subject="chore: \x1b[2Jclear", paths=("tools/a\nb\x1b.py",))])

    assert not [line for line in lines if "\x1b" in line or "\n" in line]


@pytest.mark.usefixtures("terminal")
@pytest.mark.parametrize(("reply", "expected"), [("yes", True), ("y", False), ("", False)])
def test_only_yes_confirms(monkeypatch: pytest.MonkeyPatch, reply: str, expected: bool) -> None:
    answers(monkeypatch, reply)

    assert ask([stop()]) is expected


@pytest.mark.usefixtures("terminal")
def test_v_shows_the_diff_and_asks_again(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = answers(monkeypatch, "v", "v", "yes")
    paged: list[str] = []
    monkeypatch.setattr(review, "page", lambda stops: paged.append(stops[0].layer.id))

    assert ask([stop()]) is True
    assert paged == ["0001a", "0001a"]
    assert len(prompts) == 3


@pytest.mark.usefixtures("terminal")
def test_input_that_ends_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    answers(monkeypatch)

    assert ask([stop()]) is False


def test_with_no_terminal_it_refuses_without_asking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    prompts = answers(monkeypatch, "yes")

    assert ask([stop()]) is False
    assert prompts == []


@pytest.mark.usefixtures("terminal")
def test_the_diff_is_paged_by_less_with_its_own_options_replacing_the_readers(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[tuple[list[str], dict]] = []
    monkeypatch.setenv("LESS", "FRX")
    monkeypatch.setattr(review.subprocess, "run", lambda argv, **kwargs: runs.append((argv, kwargs)) or subprocess.CompletedProcess(argv, 0))

    page([stop(diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n--- gone\n+\x1b[8mnew\n")])

    ((argv, kwargs),) = runs
    text = kwargs["input"].decode()
    assert argv == ["less"]
    assert kwargs["env"]["LESS"] == "R"
    assert "\x1b[31m--- gone\x1b[0m" in text
    assert "\x1b[32m+\\x1b[8mnew\x1b[0m" in text
    assert "\x1b[1m--- a/x\x1b[0m" in text


@pytest.mark.usefixtures("terminal")
def test_the_diff_is_printed_when_there_is_no_pager(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def missing(argv: list[str], **kwargs: object) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(review.subprocess, "run", missing)

    page([stop()])

    assert capsys.readouterr().out == "commit 0001a: chore: change a tool\n+print()\n\n"
