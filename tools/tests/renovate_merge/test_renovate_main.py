import io
import json
import subprocess
from pathlib import Path

import pytest
from _bodies import BREAKING_NOTES, body
from _promote_repo import make_remote
from conftest import FakeGitHub
from renovate_merge import __main__ as cli


@pytest.fixture
def two_pulls(github: FakeGitHub) -> tuple[int, int]:
    return github.add_pull(), github.add_pull(description=body("example/tool", "1.9.9", "2.0.0", BREAKING_NOTES))


def write_summary(github: FakeGitHub, tmp_path: Path) -> Path:
    assert cli.main(["summary", "--repo", str(tmp_path), "--out", str(tmp_path / "out")]) == 0
    return tmp_path / "out" / "summary.json"


def test_summary_prints_and_writes_the_markdown_and_the_json(
    github: FakeGitHub, two_pulls: tuple[int, int], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_summary(github, tmp_path)

    printed = capsys.readouterr()
    assert (tmp_path / "out" / "summary.md").read_text() == printed.out.removesuffix("\n")
    assert "# Renovate pull requests into `maintenance`" in printed.out
    assert f"wrote {tmp_path / 'out' / 'summary.md'}" in printed.err
    assert [(item["number"], item["level"]) for item in json.loads(path.read_text())["pulls"]] == [(1, "none"), (2, "breaking")]


def test_summary_writes_into_the_git_directory_by_default(github: FakeGitHub, two_pulls: tuple[int, int], tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    assert cli.main(["summary", "--repo", str(tmp_path)]) == 0

    assert (tmp_path / ".git" / "renovate-merge" / "summary.json").is_file()


class Terminal(io.StringIO):
    """A standard input that is a terminal and answers with what it was given."""

    def isatty(self) -> bool:
        return True


@pytest.fixture
def main_pulls(github: FakeGitHub, tmp_path: Path) -> Path:
    github.add_pull(base="main")
    github.add_pull(base="main", description=body("example/tool", "1.9.9", "2.0.0", BREAKING_NOTES))
    assert cli.main(["summary", "--repo", str(tmp_path), "--base", "main", "--allow-main", "--out", str(tmp_path / "out")]) == 0
    return tmp_path / "out" / "summary.json"


def test_summary_refuses_main_without_the_flag(github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    github.add_pull(base="main")

    assert cli.main(["summary", "--repo", str(tmp_path), "--base", "main", "--out", str(tmp_path / "out")]) == 1

    assert "main is not read without --allow-main" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_summary_reads_the_pull_requests_into_main_with_the_flag(main_pulls: Path) -> None:
    record = json.loads(main_pulls.read_text())

    assert record["base"] == "main"
    assert [(item["number"], item["level"]) for item in record["pulls"]] == [(1, "none"), (2, "breaking")]
    assert (main_pulls.parent / "summary.md").read_text().startswith("# Renovate pull requests into `main`")


def test_merge_refuses_a_summary_of_main_without_the_flag(github: FakeGitHub, main_pulls: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["merge", str(main_pulls), "--repo", str(tmp_path)]) == 1

    assert "merging into main needs --allow-main" in capsys.readouterr().err
    assert github.merged() == []


def test_merge_refuses_the_flag_with_yes_and_merges_nothing(github: FakeGitHub, main_pulls: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["merge", str(main_pulls), "--repo", str(tmp_path), "--allow-main", "--yes"]) == 1

    assert "--allow-main cannot be combined with --yes" in capsys.readouterr().err
    assert github.merged() == []


def test_merge_into_main_merges_once_the_branch_name_is_typed(
    github: FakeGitHub, main_pulls: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", Terminal("main\n"))

    assert cli.main(["merge", str(main_pulls), "--repo", str(tmp_path), "--allow-main"]) == 0

    assert github.merged() == [1]
    assert "Type 'main' to merge them" in capsys.readouterr().out


@pytest.mark.parametrize("typed", [pytest.param("yes\n", id="yes"), pytest.param("\n", id="nothing")])
def test_merge_into_main_merges_nothing_unless_the_branch_name_is_typed(
    github: FakeGitHub, main_pulls: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, typed: str
) -> None:
    monkeypatch.setattr("sys.stdin", Terminal(typed))

    assert cli.main(["merge", str(main_pulls), "--repo", str(tmp_path), "--allow-main"]) == 1

    assert github.merged() == []


def test_merge_into_another_branch_is_still_confirmed_with_yes(
    github: FakeGitHub, two_pulls: tuple[int, int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_summary(github, tmp_path)
    monkeypatch.setattr("sys.stdin", Terminal("yes\n"))

    assert cli.main(["merge", str(path), "--repo", str(tmp_path)]) == 0

    assert github.merged() == [1]


def test_merge_with_no_numbers_merges_only_the_pull_requests_at_level_none(
    github: FakeGitHub, two_pulls: tuple[int, int], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_summary(github, tmp_path)

    assert cli.main(["merge", str(path), "--repo", str(tmp_path), "--yes"]) == 0

    assert github.merged() == [1]
    assert "#1  merged  https://example.test/pull/1" in capsys.readouterr().out


def test_merge_names_a_flagged_pull_request_to_merge_it(github: FakeGitHub, two_pulls: tuple[int, int], tmp_path: Path) -> None:
    path = write_summary(github, tmp_path)

    assert cli.main(["merge", str(path), "2", "--repo", str(tmp_path), "--yes"]) == 0

    assert github.merged() == [2]


def test_merge_without_a_terminal_or_yes_merges_nothing(
    github: FakeGitHub, two_pulls: tuple[int, int], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_summary(github, tmp_path)

    assert cli.main(["merge", str(path), "--repo", str(tmp_path)]) == 1

    assert "not confirmed" in capsys.readouterr().err
    assert github.merged() == []


def test_merge_exits_1_and_says_why_when_a_pull_request_was_left(
    github: FakeGitHub, two_pulls: tuple[int, int], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_summary(github, tmp_path)
    state = github.state()
    state["prs"][0]["listed"]["headRefOid"] = "f" * 40
    github.save(state)
    capsys.readouterr()

    assert cli.main(["merge", str(path), "--repo", str(tmp_path), "--yes"]) == 1

    assert "#1  not merged: its head moved from 0000001 to fffffff" in capsys.readouterr().out


def test_merge_dry_run_exits_0_and_merges_nothing(github: FakeGitHub, two_pulls: tuple[int, int], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_summary(github, tmp_path)
    capsys.readouterr()

    assert cli.main(["merge", str(path), "--repo", str(tmp_path), "--dry-run"]) == 0

    assert "#1  not merged: dry run: ready to merge" in capsys.readouterr().out
    assert github.merged() == []


def test_merge_refuses_a_file_that_is_not_a_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bogus = tmp_path / "x.json"
    bogus.write_text("{}")

    assert cli.main(["merge", str(bogus), "--repo", str(tmp_path), "--yes"]) == 1

    assert "not a summary written by" in capsys.readouterr().err


def test_merge_reports_a_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["merge", str(tmp_path / "absent.json"), "--repo", str(tmp_path), "--yes"]) == 1

    assert "absent.json" in capsys.readouterr().err


@pytest.fixture
def promotable(github: FakeGitHub, tmp_path: Path) -> Path:
    remote = make_remote(tmp_path)
    remote.merge_pull(1, "renovate/a")
    remote.push()
    github.add_pull(state_name="MERGED", branch="renovate/a")
    return remote.clone


def test_promote_opens_the_pull_request_and_says_the_merge_is_left_to_the_maintainer(
    github: FakeGitHub, promotable: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["promote", "--repo", str(promotable), "--yes"]) == 0

    out = capsys.readouterr().out
    assert "Opened https://example.test/pull/2" in out
    assert "never merges into main" in out
    assert [created["baseRefName"] for created in github.created()] == ["main"]
    assert github.merged() == []


def test_promote_dry_run_prints_the_title_and_description_and_opens_nothing(github: FakeGitHub, promotable: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["promote", "--repo", str(promotable), "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert out.startswith("chore(deps): promote 1 update from maintenance")
    assert "| #1 |" in out
    assert github.created() == []


def test_promote_reports_a_pull_request_that_is_open_already(github: FakeGitHub, promotable: Path, capsys: pytest.CaptureFixture[str]) -> None:
    github.add_pull(branch="maintenance", base="main", login="someone")

    assert cli.main(["promote", "--repo", str(promotable), "--yes"]) == 0

    assert "Already open: https://example.test/pull/2\nIts description was not changed." in capsys.readouterr().out
    assert github.created() == []


def test_promote_without_a_terminal_or_yes_opens_nothing(github: FakeGitHub, promotable: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["promote", "--repo", str(promotable)]) == 1

    assert "not confirmed" in capsys.readouterr().err
    assert github.created() == []


def test_merge_waits_for_the_checks_named_on_the_command_line(github: FakeGitHub, tmp_path: Path) -> None:
    github.add_pull(checks=[[["lint", "pass"], ["tests", "pass"]]])
    path = write_summary(github, tmp_path)
    state = github.state()
    state["rules_error"] = "HTTP 403"
    github.save(state)

    assert cli.main(["merge", str(path), "--repo", str(tmp_path), "--yes", "--require-check", "lint", "--require-check", "tests"]) == 0

    assert github.merged() == [1]
