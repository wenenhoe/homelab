"""Tests for ci.branches.realign, on real repositories in a temporary directory.

Each test builds a bare `origin` with `main` and `maintenance` and a clone to
run in, the way the workflow's checkout looks. The assertions read `origin`
afterwards: `main` never moves, `maintenance` only grows, and a conflict
leaves it exactly where it was.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from ci import proc
from ci.branches import realign

NAME = "Realign Test"
EMAIL = "realign@example.invalid"


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


class Repos:
    def __init__(self, base: Path):
        self.origin = base / "origin.git"
        self.work = base / "work"
        self.other = base / "other"
        git(base, "init", "--bare", "--initial-branch=main", str(self.origin))
        git(base, "clone", "--quiet", str(self.origin), str(self.other))
        git(self.other, "checkout", "-b", "main")
        self.commit(self.other, "base.txt", "base\n")
        git(self.other, "push", "--quiet", "origin", "main")
        git(self.other, "push", "--quiet", "origin", "main:maintenance")

    def commit(self, repo: Path, path: str, text: str, branch: str | None = None) -> str:
        if branch:
            git(repo, "checkout", "--quiet", branch)
        (repo / path).write_text(text)
        git(repo, "add", path)
        git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", f"change {path}")
        return git(repo, "rev-parse", "HEAD")

    def advance(self, branch: str, path: str, text: str) -> str:
        """Add a commit to one of origin's branches."""
        git(self.other, "fetch", "--quiet", "origin")
        git(self.other, "checkout", "--quiet", "-B", branch, f"origin/{branch}")
        sha = self.commit(self.other, path, text)
        git(self.other, "push", "--quiet", "origin", branch)
        return sha

    def checkout(self) -> None:
        git(self.origin.parent, "clone", "--quiet", str(self.origin), str(self.work))

    def tip(self, branch: str) -> str:
        return git(self.origin, "rev-parse", f"refs/heads/{branch}")

    def is_ancestor(self, older: str, newer: str) -> bool:
        return subprocess.run(["git", "merge-base", "--is-ancestor", older, newer], cwd=self.origin, check=False).returncode == 0


class Recorder:
    """The real runner, remembering every command."""

    def __init__(self):
        self.commands: list[list[str]] = []

    def __call__(self, args, cwd, capture=False):
        self.commands.append(args)
        return proc.run(args, cwd, capture)

    def pushes(self) -> list[list[str]]:
        return [c for c in self.commands if "push" in c]


@pytest.fixture
def repos(tmp_path):
    return Repos(tmp_path)


def run_realign(repos: Repos, recorder: Recorder | None = None) -> int:
    repos.checkout()
    return realign.main(["--name", NAME, "--email", EMAIL], runner=recorder or Recorder(), root=repos.work)


class TestAlreadyCurrent:
    def test_equal_branches_are_left_alone(self, repos):
        main, maintenance = repos.tip("main"), repos.tip("maintenance")
        recorder = Recorder()
        assert run_realign(repos, recorder) == 0
        assert (repos.tip("main"), repos.tip("maintenance")) == (main, maintenance)
        assert recorder.pushes() == []

    def test_a_maintenance_ahead_of_main_is_left_alone(self, repos):
        repos.advance("maintenance", "dep.txt", "bump\n")
        maintenance = repos.tip("maintenance")
        recorder = Recorder()
        assert run_realign(repos, recorder) == 0
        assert repos.tip("maintenance") == maintenance
        assert recorder.pushes() == []


class TestFastForward:
    def test_maintenance_lands_exactly_on_main(self, repos):
        main = repos.advance("main", "fix.txt", "fix\n")
        assert run_realign(repos) == 0
        assert repos.tip("maintenance") == main
        assert repos.tip("main") == main

    def test_no_merge_commit_is_made(self, repos):
        before = repos.tip("maintenance")
        repos.advance("main", "fix.txt", "fix\n")
        run_realign(repos)
        assert git(repos.origin, "rev-list", "--merges", f"{before}..maintenance") == ""


class TestMerge:
    def test_diverged_branches_get_a_merge_commit(self, repos, subtests):
        old_tip = repos.advance("maintenance", "dep.txt", "bump\n")
        main = repos.advance("main", "fix.txt", "fix\n")
        assert run_realign(repos) == 0
        tip = repos.tip("maintenance")
        with subtests.test("two parents, the old tip first"):
            assert git(repos.origin, "rev-list", "--parents", "-n1", tip).split()[1:] == [old_tip, main]
        with subtests.test("the old tip is kept, not rewritten"):
            assert repos.is_ancestor(old_tip, tip)
        with subtests.test("both changes are present"):
            assert git(repos.origin, "ls-tree", "--name-only", tip).split() == ["base.txt", "dep.txt", "fix.txt"]
        with subtests.test("main did not move"):
            assert repos.tip("main") == main
        with subtests.test("the commit has the given author and a plain message"):
            assert git(repos.origin, "log", "-1", "--format=%an <%ae>|%s", tip) == f"{NAME} <{EMAIL}>|Merge main into maintenance"

    def test_a_second_run_changes_nothing(self, repos):
        repos.advance("maintenance", "dep.txt", "bump\n")
        repos.advance("main", "fix.txt", "fix\n")
        run_realign(repos)
        tip = repos.tip("maintenance")
        recorder = Recorder()
        shutil.rmtree(repos.work)
        assert run_realign(repos, recorder) == 0
        assert repos.tip("maintenance") == tip
        assert recorder.pushes() == []


class TestConflict:
    @pytest.fixture
    def conflicted(self, repos):
        repos.advance("maintenance", "shared.txt", "from maintenance\n")
        repos.advance("main", "shared.txt", "from main\n")
        return repos

    def test_the_run_fails_and_maintenance_is_unchanged(self, conflicted, capsys, subtests):
        main, maintenance = conflicted.tip("main"), conflicted.tip("maintenance")
        recorder = Recorder()
        assert run_realign(conflicted, recorder) == 1
        with subtests.test("maintenance is where it was"):
            assert conflicted.tip("maintenance") == maintenance
        with subtests.test("main is where it was"):
            assert conflicted.tip("main") == main
        with subtests.test("nothing was pushed"):
            assert recorder.pushes() == []
        with subtests.test("the merge was aborted, leaving a clean tree"):
            assert git(conflicted.work, "status", "--porcelain") == ""
        with subtests.test("the error names the conflict"):
            assert "conflicts with maintenance" in capsys.readouterr().err

    def test_control_the_conflict_is_real(self, conflicted):
        # Without this the test above could pass on branches that merge cleanly.
        conflicted.checkout()
        git(conflicted.work, "checkout", "--quiet", "--detach", conflicted.tip("maintenance"))
        result = subprocess.run(
            ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "merge", conflicted.tip("main")],
            cwd=conflicted.work,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert "CONFLICT" in result.stdout


class TestNeverForces:
    @pytest.mark.parametrize("case", ["fast-forward", "merge"], ids=str)
    def test_pushes_name_only_maintenance_and_never_force(self, repos, case, subtests):
        if case == "merge":
            repos.advance("maintenance", "dep.txt", "bump\n")
        repos.advance("main", "fix.txt", "fix\n")
        recorder = Recorder()
        assert run_realign(repos, recorder) == 0
        pushes = recorder.pushes()
        assert len(pushes) == 1
        for argument in pushes[0]:
            with subtests.test(argument=argument):
                assert argument != "--force"
                assert not argument.startswith(("+", "--force", "--mirror", "--delete"))
        assert pushes[0][-1].endswith(":refs/heads/maintenance")

    def test_a_branch_that_moved_meanwhile_is_not_overwritten(self, repos, capsys):
        repos.advance("main", "fix.txt", "fix\n")

        class Racing(Recorder):
            def __call__(self, args, cwd, capture=False):
                if "push" in args:
                    repos.advance("maintenance", "late.txt", "arrived during the run\n")
                return super().__call__(args, cwd, capture)

        assert run_realign(repos, Racing()) == 1
        late = repos.tip("maintenance")
        assert git(repos.origin, "show", f"{late}:late.txt") == "arrived during the run"
        assert "refused" in capsys.readouterr().err


class TestMissingBranch:
    def test_no_maintenance_on_origin_fails(self, repos, capsys):
        git(repos.origin, "branch", "-D", "maintenance")
        assert run_realign(repos) == 1
        assert "maintenance" in capsys.readouterr().err
