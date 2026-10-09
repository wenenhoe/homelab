"""Tests for ci.scope.effective_changes against a real git history.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from ci.scope import effective_changes as ec

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
PY = "ansible/tests/test_x.py"
PYPROJECT = '[project]\nname = "x"\ndependencies = ["a>=1"]\n\n[tool.ruff]\nline-length = 160\n'


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.base = ""

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


@pytest.fixture
def repo(root):
    repo = Repo(root)
    repo.git("init", "-q")
    repo.write(PY, "def test():\n    assert 1\n")
    repo.write("tools/tests/test_y.py", "def test():\n    assert 2\n")
    repo.write("pyproject.toml", PYPROJECT)
    repo.write("uv.lock", 'version = 1\n[[package]]\nname = "a"\n')
    repo.base = repo.commit("base")
    return repo


@pytest.fixture
def evaluate(repo, monkeypatch):
    def run(**files: list[str]) -> dict[str, bool]:
        head = repo.commit("change")
        for name, paths in files.items():
            monkeypatch.setenv(f"{name.upper()}_FILES", json.dumps(paths))
        return ec.evaluate(repo.root, repo.base, head, list(files))

    return run


class TestEffectiveChanges:
    def test_comment_only_change_leaves_the_filter_false(self, repo, evaluate):
        repo.write(PY, "# note\ndef test():\n    assert 1\n")
        assert evaluate(python_unit_tests=[PY]) == {"python_unit_tests": False}

    def test_real_change_makes_the_filter_true(self, repo, evaluate):
        repo.write(PY, "def test():\n    assert 3\n")
        assert evaluate(python_unit_tests=[PY]) == {"python_unit_tests": True}

    def test_one_real_change_among_no_ops_is_enough(self, repo, evaluate):
        repo.write(PY, "# note\ndef test():\n    assert 1\n")
        repo.write("tools/tests/test_y.py", "def test():\n    assert 9\n")
        assert evaluate(python_unit_tests=[PY, "tools/tests/test_y.py"])["python_unit_tests"]

    def test_no_matched_files_is_false(self, evaluate):
        assert evaluate(uv_lock=[]) == {"uv_lock": False}

    def test_ruff_only_pyproject_change_leaves_lock_and_deploy_filters_false(self, repo, evaluate):
        repo.write("pyproject.toml", PYPROJECT.replace("160", "100"))
        result = evaluate(uv_lock=["pyproject.toml"], deploy_ordering=["pyproject.toml"], python_unit_tests=["pyproject.toml"])
        assert result == {"uv_lock": False, "deploy_ordering": False, "python_unit_tests": False}

    def test_dependency_change_makes_every_filter_true(self, repo, evaluate):
        repo.write("pyproject.toml", PYPROJECT.replace("a>=1", "a>=2"))
        result = evaluate(uv_lock=["pyproject.toml"], deploy_ordering=["pyproject.toml"], python_unit_tests=["pyproject.toml"])
        assert set(result.values()) == {True}

    def test_lock_change_is_real(self, repo, evaluate):
        repo.write("uv.lock", 'version = 1\n[[package]]\nname = "b"\n')
        assert evaluate(uv_lock=["uv.lock"])["uv_lock"]

    def test_deleted_file_is_real(self, repo, evaluate):
        (repo.root / PY).unlink()
        assert evaluate(python_unit_tests=[PY])["python_unit_tests"]

    @pytest.mark.parametrize("name", ["ansible_lint", "trivy_ansible"])
    def test_gated_filters_never_include_the_ones_that_read_comments(self, repo, monkeypatch, name):
        monkeypatch.setenv(f"{name.upper()}_FILES", "[]")
        with pytest.raises(ec.FilterError, match="can't be gated"):
            ec.evaluate(repo.root, repo.base, repo.base, [name])

    def test_a_missing_file_list_is_an_error(self, monkeypatch):
        monkeypatch.delenv("UV_LOCK_FILES", raising=False)
        with pytest.raises(ec.FilterError, match="UV_LOCK_FILES is not set"):
            ec.files_from_env("uv_lock")

    @pytest.mark.parametrize(
        "bad",
        [pytest.param("not json", id="not-json"), pytest.param('{"a": 1}', id="an-object"), pytest.param("[1, 2]", id="not-strings")],
    )
    def test_a_malformed_file_list_is_an_error(self, monkeypatch, bad):
        monkeypatch.setenv("UV_LOCK_FILES", bad)
        with pytest.raises(ec.FilterError):
            ec.files_from_env("uv_lock")

    def test_main_writes_every_filter_to_the_output_file(self, repo, monkeypatch):
        repo.write(PY, "# note\ndef test():\n    assert 1\n")
        repo.write("uv.lock", 'version = 1\n[[package]]\nname = "b"\n')
        head = repo.commit("change")
        out = repo.root / "out.txt"
        env = {"GITHUB_OUTPUT": str(out), "PYTHON_UNIT_TESTS_FILES": json.dumps([PY]), "UV_LOCK_FILES": json.dumps(["uv.lock"])}
        monkeypatch.setattr(ec, "REPO_ROOT", repo.root)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        assert ec.main([repo.base, head, "python_unit_tests", "uv_lock"]) == 0
        assert out.read_text().splitlines() == ["python_unit_tests=false", "uv_lock=true"]

    def test_main_fails_on_a_bad_filter(self, repo, monkeypatch):
        monkeypatch.setattr(ec, "REPO_ROOT", repo.root)
        monkeypatch.setenv("ANSIBLE_LINT_FILES", "[]")
        assert ec.main([repo.base, repo.base, "ansible_lint"]) == 1
