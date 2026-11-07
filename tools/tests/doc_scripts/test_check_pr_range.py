"""Tests for check_pr_range.py against real temporary git repositories: the pre-push
runner of the four pull-request checks. Run via `uv run pytest tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from _doc_fixtures import GitRepo, revision
from doc_scripts import check_accepted_records, check_project_scope
from doc_scripts import check_pr_range as cli

PROJECT = "docs/projects/p.md"
PROJECT_DOC = """---
id: PROJ-p
title: p
type: project
status: building
summary: s
allowed_paths:
  - 'src/**'
---

# p

## Execution plan

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | First | {stage} | done |
"""
DECISION = "# T\n\n## Decision\n\n{text}\n"
TRAILER = "Editorial-Fix: docs/decisions/0050-x/revision-000.md"


@pytest.fixture
def repo(root: Path) -> GitRepo:
    repo = GitRepo(root, cli)
    repo.git("init", "-q")
    repo.git("checkout", "-q", "-b", "main")
    repo.write(PROJECT, PROJECT_DOC.format(stage="Not started"))
    repo.write("src/a.py", "a = 1\n")
    repo.write("other/b.py", "b = 1\n")
    revision(root, "0050-x", 0, body=DECISION.format(text="Use one."), status="accepted")
    repo.commit("base")
    return repo


def push(repo: GitRepo, *args: str) -> tuple[int, str]:
    return repo.run_cli(*args)


class TestDefaultBranch:
    def test_the_remote_head_wins(self, repo):
        repo.git("update-ref", "refs/remotes/origin/trunk", "main")
        repo.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        assert cli.default_branch(repo.root) == "origin/trunk"

    def test_without_a_remote_head_the_remote_main_is_next(self, repo):
        repo.git("update-ref", "refs/remotes/origin/main", "main")
        assert cli.default_branch(repo.root) == "origin/main"

    def test_a_local_main_is_the_last_resort(self, repo):
        assert cli.default_branch(repo.root) == "main"

    def test_a_remote_other_than_origin_is_asked_for_by_name(self, repo):
        repo.git("update-ref", "refs/remotes/upstream/main", "main")
        assert cli.default_branch(repo.root, "upstream") == "upstream/main"

    def test_no_default_branch_is_none(self, repo):
        repo.git("branch", "-m", "main", "work")
        assert cli.default_branch(repo.root) is None


class TestChecks:
    def test_a_branch_inside_its_scope_passes(self, repo):
        repo.branch()
        repo.write("src/a.py", "a = 2\n")
        repo.write(PROJECT, PROJECT_DOC.format(stage="In progress"))
        repo.commit("work")
        code, out = push(repo)
        assert code == 0, out
        assert "Checking HEAD against main" in out

    def test_a_stray_file_in_an_earlier_commit_fails_and_the_staged_form_misses_it(self, repo):
        repo.branch()
        repo.write("other/b.py", "b = 2\n")
        repo.write(PROJECT, PROJECT_DOC.format(stage="In progress"))
        repo.commit("stray")
        repo.write("src/a.py", "a = 2\n")
        repo.commit("later")
        code, out = push(repo)
        assert code == 1
        assert "other/b.py" in out
        assert "Failed: check_project_scope" in out
        # Control: the commit-time form judges only what is staged, which is nothing here.
        assert check_project_scope.main(["--staged", "--root", str(repo.root)]) == 0

    def test_a_frozen_section_change_fails_until_a_commit_carries_the_trailer(self, repo):
        repo.branch()
        revision(repo.root, "0050-x", 0, body=DECISION.format(text="Use two."), status="accepted")
        repo.commit("change what was decided")
        code, out = push(repo)
        assert code == 1
        assert "Decision" in out
        assert "Failed: check_accepted_records" in out
        # Control: the commit-time form only warns, since the trailer is not written yet.
        repo.write("x.txt", "x\n")
        repo.git("add", "-A")
        assert check_accepted_records.main(["--staged", "--root", str(repo.root)]) == 0
        repo.git("reset", "-q", "--hard")
        repo.git("commit", "-q", "--amend", "-m", f"fix: reword\n\n{TRAILER}")
        code, out = push(repo)
        assert code == 0, out

    def test_every_check_runs_even_when_an_earlier_one_fails(self, repo, monkeypatch):
        calls = []

        def fake(name, code):
            return SimpleNamespace(__name__=f"doc_scripts.{name}", main=lambda argv: calls.append((name, argv)) or code)

        monkeypatch.setattr(cli, "CHECKS", (fake("first", 1), fake("second", 0), fake("third", 1)))
        repo.branch()
        repo.write("src/a.py", "a = 2\n")
        repo.commit("work")
        code, out = push(repo)
        assert code == 1
        assert [name for name, _ in calls] == ["first", "second", "third"]
        assert calls[0][1] == ["--base", "main", "--head", "HEAD", "--root", str(repo.root)]
        assert "Failed: first, third" in out

    def test_the_head_comes_from_the_ref_being_pushed(self, repo, monkeypatch):
        repo.branch("pushed")
        repo.write("other/b.py", "b = 2\n")
        repo.write(PROJECT, PROJECT_DOC.format(stage="In progress"))
        repo.commit("stray")
        repo.git("checkout", "-q", "main")
        assert push(repo)[0] == 0
        monkeypatch.setenv("PRE_COMMIT_TO_REF", repo.git("rev-parse", "pushed").strip())
        assert push(repo)[0] == 1

    def test_an_explicit_base_replaces_the_default_branch(self, repo):
        repo.branch()
        repo.write("other/b.py", "b = 2\n")
        repo.write(PROJECT, PROJECT_DOC.format(stage="In progress"))
        repo.commit("stray")
        assert push(repo, "--base", "HEAD")[0] == 0
        assert push(repo, "--base", "main")[0] == 1


class TestSkipped:
    def test_no_default_branch_skips_and_says_ci_runs_them(self, repo):
        repo.git("branch", "-m", "main", "work")
        code, out = push(repo)
        assert code == 0
        assert "No default branch found" in out
        assert "CI runs them" in out

    def test_a_head_with_no_shared_history_skips(self, repo):
        repo.git("checkout", "-q", "--orphan", "unrelated")
        repo.write("src/a.py", "a = 1\n")
        repo.commit("root")
        code, out = push(repo)
        assert code == 0
        assert "shares no history" in out

    def test_a_branch_that_adds_nothing_skips(self, repo):
        code, out = push(repo)
        assert code == 0
        assert "adds no commit" in out

    def test_deleting_a_ref_skips(self, repo):
        code, out = push(repo, "--head", "0" * 40)
        assert code == 0
        assert "deleted" in out
