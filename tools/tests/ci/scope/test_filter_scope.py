"""Tests for ci.scope.filter_scope: a path filter evaluated for a range of commits in a real git history."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from ci.scope import filter_scope as fs

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
FILTERS = "python_unit_tests:\n  - 'ansible/scripts/*.py'\n  - 'tools/**'\nuv_lock:\n  - 'uv.lock'\nansible_lint:\n  - 'ansible/**'\n"


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.git("init", "-q")
        self.write(fs.FILTERS_FILE, FILTERS)
        self.write("tools/tests/test_x.py", "def test():\n    assert 1\n")
        self.write("README.md", "hello\n")
        self.base = self.commit("base")

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, env={**os.environ, **GIT_ENV}, capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def is_true(self, name: str = "python_unit_tests") -> bool:
        return fs.is_true(self.root, self.base, self.commit("change"), name)


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)


def test_a_real_change_under_a_matching_glob_makes_the_filter_true(repo: Repo) -> None:
    repo.write("tools/tests/test_x.py", "def test():\n    assert 2\n")

    assert repo.is_true()


def test_a_new_file_under_a_recursive_glob_makes_the_filter_true(repo: Repo) -> None:
    repo.write("tools/new_package/module.py", "VALUE = 1\n")

    assert repo.is_true()


def test_a_change_outside_every_glob_leaves_the_filter_false(repo: Repo) -> None:
    repo.write("README.md", "changed\n")

    assert not repo.is_true()


def test_a_star_glob_does_not_reach_into_a_subdirectory(repo: Repo) -> None:
    repo.write("ansible/scripts/nested/script.py", "VALUE = 1\n")

    assert not repo.is_true()


def test_a_comment_only_change_does_not_make_the_filter_true(repo: Repo) -> None:
    repo.write("tools/tests/test_x.py", "# a note\ndef test():\n    assert 1\n")

    assert not repo.is_true()


@pytest.mark.parametrize("name", ["ansible_lint", "trivy_ansible"])
def test_a_filter_that_must_not_be_gated_is_refused(repo: Repo, name: str) -> None:
    repo.write("ansible/x.yaml", "a: 1\n")

    with pytest.raises(fs.FilterScopeError, match="not gated"):
        repo.is_true(name)


def test_a_filter_the_file_does_not_have_is_an_error(repo: Repo) -> None:
    with pytest.raises(fs.FilterScopeError, match="no filter 'missing'"):
        repo.is_true("missing")


def test_the_verdict_is_written_the_way_a_workflow_step_output_is(repo: Repo, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    repo.write("tools/tests/test_x.py", "def test():\n    assert 2\n")
    head = repo.commit("change")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr(fs, "REPO_ROOT", repo.root)

    status = fs.main(["--base", repo.base, "--head", head, "python_unit_tests"])

    assert status == 0
    assert capsys.readouterr().out == "python_unit_tests=true\n"
