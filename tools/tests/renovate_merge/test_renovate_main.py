import json
import subprocess
from pathlib import Path

import pytest
from _bodies import BREAKING_NOTES, body
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


def test_summary_refuses_main(github: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["summary", "--repo", str(tmp_path), "--base", "main", "--out", str(tmp_path / "out")]) == 1

    assert "never merges there" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()
