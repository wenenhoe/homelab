"""Replaying a series on a scratch worktree, and the command line around it."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from _series_repo import Author, Repo, git, series_file
from land_series import __main__ as cli
from land_series.manifest import Layer, order_layers, parse_series
from land_series.replay import Check, ReplayError, replay

# Appends one line per run to the log: each named file's contents, with newlines shown as "/", so a test reads back the tree a check saw.
RECORD = (
    "import os, pathlib, sys\n"
    "text = (pathlib.Path(name).read_text().strip().replace(chr(10), '/') for name in sys.argv[1:])\n"
    "open(os.environ['LAND_LOG'], 'a').write(' '.join(text) + chr(10))\n"
)
FAIL = RECORD + "print('lint says no', file=sys.stderr)\nsys.exit(1)\n"


class Confirmations:
    """Answers the stop prompt with a fixed reply and remembers what it was asked."""

    def __init__(self, answer: bool) -> None:
        self.answer = answer
        self.asked: list[tuple[str, list[str]]] = []

    def __call__(self, layer: Layer, paths: Sequence[str]) -> bool:
        self.asked.append((layer.id, list(paths)))
        return self.answer


@pytest.fixture
def log(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The file the recording check appends a line to per run; absent until a check runs."""
    path = tmp_path_factory.mktemp("log") / "checks.log"
    monkeypatch.setenv("LAND_LOG", str(path))
    return path


def recording_check(*files: str, script: str = RECORD) -> Check:
    return Check((sys.executable, "-c", script, *files))


def layers_of(*patches: tuple[str, bytes]) -> list[Layer]:
    return order_layers(parse_series(series_file([(f"{layer_id} slug-{layer_id}", patch) for layer_id, patch in patches])))


def test_each_layer_is_checked_on_the_tree_the_layers_before_it_made(repo: Repo, author: Author, log: Path) -> None:
    layers = layers_of(
        ("0001a", author.patch("docs: write one", {"a.txt": "one\n"})),
        ("0001b", author.patch("docs: write two", {"a.txt": "two\n"})),
    )
    main_before = git(repo.path, "rev-parse", "main")

    results = replay(repo.path, layers, [recording_check("a.txt")], Confirmations(False), base="main")

    assert log.read_text().splitlines() == ["one", "two"]
    assert [(result.layer.id, result.applied) for result in results] == [("0001a", True), ("0001b", True)]
    assert git(repo.path, "rev-parse", "main") == main_before
    assert len(repo.worktrees()) == 1


def test_files_an_apply_hook_leaves_behind_are_dropped_before_the_checks_and_the_next_layer(repo: Repo, author: Author, log: Path, tmp_path: Path) -> None:
    hook_runs = tmp_path / "hook-runs"
    repo.install_hook("post-applypatch", f"echo ran >> {hook_runs}\necho regenerated >> base.txt\n")
    layers = layers_of(
        ("0001a", author.patch("docs: one", {"base.txt": "base\none\n"})),
        ("0001b", author.patch("docs: two", {"base.txt": "base\none\ntwo\n"})),
    )

    results = replay(repo.path, layers, [recording_check("base.txt")], Confirmations(False), base="main")

    assert hook_runs.read_text().splitlines() == ["ran", "ran"]
    assert log.read_text().splitlines() == ["base/one", "base/one/two"]
    assert all(result.applied for result in results)


def test_a_layer_already_in_the_base_is_skipped_and_the_ones_after_it_replay(repo: Repo, author: Author, log: Path) -> None:
    first = author.patch("docs: write one", {"a.txt": "one\n"})
    second = author.patch("docs: write two", {"a.txt": "two\n"})
    git(repo.path, "am", "--quiet", stdin=first)

    results = replay(repo.path, layers_of(("0001a", first), ("0001b", second)), [recording_check("a.txt")], Confirmations(False), base="main")

    assert [(result.layer.id, result.applied) for result in results] == [("0001a", False), ("0001b", True)]
    assert log.read_text().splitlines() == ["two"]


def test_a_failing_check_stops_the_replay_and_quotes_its_output(repo: Repo, author: Author, log: Path) -> None:
    layers = layers_of(("0001a", author.patch("docs: one", {"a.txt": "one\n"})), ("0001b", author.patch("docs: two", {"a.txt": "two\n"})))

    with pytest.raises(ReplayError, match=r"(?s)layer 0001a fails `.*`:\nlint says no"):
        replay(repo.path, layers, [recording_check("a.txt", script=FAIL)], Confirmations(False), base="main")

    assert log.read_text().splitlines() == ["one"]
    assert len(repo.worktrees()) == 1


def test_a_layer_that_does_not_apply_is_named_and_leaves_no_worktree(repo: Repo, author: Author, log: Path) -> None:
    author.patch("docs: write one", {"a.txt": "one\n"})
    second = author.patch("docs: write two", {"a.txt": "two\n"})

    with pytest.raises(ReplayError, match="layer 0001b does not apply on main"):
        replay(repo.path, layers_of(("0001b", second)), [recording_check("a.txt")], Confirmations(False), base="main")

    assert not log.exists()
    assert len(repo.worktrees()) == 1


def test_a_layer_on_the_stop_list_is_not_applied_unless_confirmed(repo: Repo, author: Author, log: Path) -> None:
    layers = layers_of(
        ("0001a", author.patch("docs: one", {"a.txt": "one\n"})),
        ("0001b", author.patch("chore: change a tool", {"tools/run.py": "print()\n"})),
    )
    refusal = Confirmations(False)

    with pytest.raises(ReplayError, match=r"layer 0001b changes code the replay runs \(tools/run.py\) and was not confirmed"):
        replay(repo.path, layers, [recording_check("a.txt")], refusal, base="main")

    assert refusal.asked == [("0001b", ["tools/run.py"])]
    assert log.read_text().splitlines() == ["one"]


def test_a_confirmed_layer_on_the_stop_list_replays(repo: Repo, author: Author, log: Path) -> None:
    layers = layers_of(("0001a", author.patch("chore: change a tool", {"tools/run.py": "print()\n"})))
    consent = Confirmations(True)

    results = replay(repo.path, layers, [recording_check("tools/run.py")], consent, base="main")

    assert consent.asked == [("0001a", ["tools/run.py"])]
    assert log.read_text().splitlines() == ["print()"]
    assert [(result.layer.id, result.applied) for result in results] == [("0001a", True)]
    assert git(repo.path, "log", "-1", "--format=%s", results[0].commit or "") == "chore: change a tool"


@pytest.mark.usefixtures("github")
def test_a_series_file_replays_and_keeps_a_branch_per_layer_from_the_command_line(
    repo: Repo, author: Author, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    patch = author.patch("docs: write one", {"a.txt": "one\n"})
    series = tmp_path / "series.txt"
    series.write_bytes(series_file([("0001a write-one", patch)]))

    status = cli.main([str(series), "--repo", str(repo.path), "--no-fetch", "--check", f"{sys.executable} -c pass"])

    assert status == 0
    assert capsys.readouterr().out.splitlines() == [
        "0001a  kept as series/write-one  docs: write one",
        "Review the branches, then run again with --land to push them.",
    ]
    assert git(repo.path, "log", "-1", "--format=%s", "series/write-one") == "docs: write one"


@pytest.mark.usefixtures("github")
def test_a_dry_run_replays_without_leaving_a_branch(repo: Repo, author: Author, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    patch = author.patch("docs: write one", {"a.txt": "one\n"})
    series = tmp_path / "series.txt"
    series.write_bytes(series_file([("0001a write-one", patch)]))

    status = cli.main([str(series), "--repo", str(repo.path), "--no-fetch", "--dry-run", "--check", f"{sys.executable} -c pass"])

    assert status == 0
    assert capsys.readouterr().out.strip() == "0001a  replayed  docs: write one"
    assert git(repo.path, "branch", "--list", "series/*") == ""


def test_land_and_dry_run_together_are_refused(repo: Repo, tmp_path: Path) -> None:
    series = tmp_path / "series.txt"
    series.write_text("")

    with pytest.raises(SystemExit):
        cli.main([str(series), "--repo", str(repo.path), "--land", "--dry-run"])


@pytest.mark.usefixtures("github")
def test_a_failing_replay_exits_one_and_says_which_layer(repo: Repo, author: Author, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    patch = author.patch("docs: write one", {"a.txt": "one\n"})
    series = tmp_path / "series.txt"
    series.write_bytes(series_file([("0001a write-one", patch)]))

    status = cli.main([str(series), "--repo", str(repo.path), "--no-fetch", "--check", f"{sys.executable} -c 'raise SystemExit(3)'"])

    assert status == 1
    assert capsys.readouterr().err.startswith("land_series: layer 0001a fails")


@pytest.mark.usefixtures("github")
def test_with_no_terminal_a_stop_list_layer_is_refused(repo: Repo, author: Author, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    patch = author.patch("chore: change a tool", {"tools/run.py": "print()\n"})
    series = tmp_path / "series.txt"
    series.write_bytes(series_file([("0001a change-tool", patch)]))

    status = cli.main([str(series), "--repo", str(repo.path), "--no-fetch", "--check", f"{sys.executable} -c pass"])

    assert status == 1
    assert "was not confirmed" in capsys.readouterr().err


def test_a_malformed_series_file_exits_one(repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    series = tmp_path / "series.txt"
    series.write_text("0001a one\n")

    status = cli.main([str(series), "--repo", str(repo.path), "--no-fetch"])

    assert status == 1
    assert "no patches" in capsys.readouterr().err


def test_fetch_brings_the_remote_base_up_to_date(repo: Repo, tmp_path_factory: pytest.TempPathFactory) -> None:
    clone = tmp_path_factory.mktemp("clone") / "work"
    git(clone.parent, "clone", "-q", str(repo.path), clone.name)
    (repo.path / "later.txt").write_text("later\n")
    git(repo.path, "add", "-A")
    git(repo.path, "commit", "-q", "-m", "docs: later")

    cli.fetch(clone, "origin/main")

    assert git(clone, "rev-parse", "origin/main") == git(repo.path, "rev-parse", "main")


def test_default_checks_are_the_scope_check_against_the_base_and_pre_commit() -> None:
    scope, hooks = cli.default_checks("origin/main")

    assert scope.argv[-2:] == ("--base", "origin/main")
    assert scope.cwd == "tools"
    assert hooks.argv == ("pre-commit", "run", "--all-files")
