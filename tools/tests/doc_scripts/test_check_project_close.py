"""Tests for check_project_close.py against a real temporary git repository -
the merge-base, index, and rename behavior is exactly what mocks would get
wrong. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from _doc_fixtures import GitRepo, project, revision
from doc_scripts import check_project_close as cli

LINEAGE = "0001-x"
REVISION = f"docs/decisions/{LINEAGE}/revision-000.md"
CLOSING = "docs/projects/closing.md"
SIBLING = "docs/projects/sibling.md"


@pytest.fixture
def repo(root: Path) -> GitRepo:
    """main holds one approved revision and two projects naming it (`closing`, `sibling`)."""
    repo = GitRepo(root, cli)
    repo.git("init", "-q")
    repo.git("checkout", "-q", "-b", "main")
    revision(root, LINEAGE, 0, status="approved")
    project(root, "closing", status="building", decision="ADR-0001/0")
    project(root, "sibling", status="not-started", decision="ADR-0001/0")
    project(root, "loner", status="building")
    repo.commit("base")
    return repo


def accept(repo: GitRepo) -> None:
    path = repo.root / REVISION
    path.write_text(path.read_text(encoding="utf-8").replace("status: approved", "status: accepted"), encoding="utf-8")


class TestPullRequestMode:
    def test_deleting_a_project_while_a_sibling_remains_passes(self, repo):
        repo.branch()
        repo.git("rm", "-q", CLOSING)
        repo.commit("close, not last")
        code, out = repo.pr()
        assert code == 0, out

    def test_deleting_the_last_project_naming_an_unaccepted_revision_fails(self, repo):
        repo.branch()
        repo.git("rm", "-q", CLOSING, SIBLING)
        repo.commit("close both")
        code, out = repo.pr()
        assert code == 1, out
        assert CLOSING in out
        assert SIBLING in out
        assert "ADR-0001/0" in out

    def test_accepting_the_revision_in_the_same_change_passes(self, repo):
        repo.branch()
        repo.git("rm", "-q", CLOSING, SIBLING)
        accept(repo)
        repo.commit("close both and accept")
        code, out = repo.pr()
        assert code == 0, out

    def test_a_successor_added_in_the_same_change_passes(self, repo):
        repo.branch()
        repo.git("rm", "-q", CLOSING, SIBLING)
        project(repo.root, "remainder", status="not-started", decision="ADR-0001/0")
        repo.commit("close both, carry the rest into a successor")
        code, out = repo.pr()
        assert code == 0, out

    def test_a_change_that_deletes_no_project_doc_is_not_checked(self, repo):
        repo.branch()
        (repo.root / CLOSING).write_text((repo.root / CLOSING).read_text(encoding="utf-8") + "\nmore\n", encoding="utf-8")
        repo.commit("edit only")
        code, out = repo.pr()
        assert code == 0, out
        assert "nothing to close-check" in out

    def test_deleting_a_project_with_no_decision_passes(self, repo):
        repo.branch()
        repo.git("rm", "-q", "docs/projects/loner.md")
        repo.commit("close loner")
        assert repo.pr()[0] == 0

    def test_a_renamed_project_doc_keeps_the_revision_named(self, repo):
        repo.branch()
        repo.git("rm", "-q", SIBLING)
        repo.git("mv", CLOSING, "docs/projects/renamed.md")
        repo.commit("rename one, close the other")
        code, out = repo.pr()
        assert code == 0, out

    def test_a_project_main_added_after_the_branch_point_is_not_a_deletion_by_the_branch(self, repo):
        repo.branch()
        (repo.root / "notes.txt").write_text("x\n", encoding="utf-8")
        repo.commit("unrelated work")
        repo.git("checkout", "-q", "main")
        revision(repo.root, "0002-y", 0, status="approved")
        project(repo.root, "late", status="not-started", decision="ADR-0002/0")
        repo.commit("main moves on")  # a diff from main's tip would show the branch as deleting late.md
        code, out = repo.pr()
        assert code == 0, out

    def test_a_result_whose_docs_do_not_parse_fails_closed(self, repo):
        repo.branch()
        repo.git("rm", "-q", CLOSING)
        (repo.root / SIBLING).write_text("no frontmatter here\n", encoding="utf-8")
        repo.commit("close one, break another")
        code, out = repo.pr()
        assert code == 1, out
        assert "missing frontmatter" in out
        assert str(repo.root) not in out


class TestStagedMode:
    def test_a_staged_deletion_of_the_last_project_fails(self, repo):
        repo.git("rm", "-q", CLOSING, SIBLING)
        code, out = repo.run_cli("--staged")
        assert code == 1, out
        assert CLOSING in out

    def test_a_staged_deletion_with_a_staged_acceptance_passes(self, repo):
        repo.git("rm", "-q", CLOSING, SIBLING)
        accept(repo)
        repo.git("add", REVISION)
        code, out = repo.run_cli("--staged")
        assert code == 0, out

    def test_an_unstaged_acceptance_does_not_count(self, repo):
        repo.git("rm", "-q", CLOSING, SIBLING)
        accept(repo)  # edited but not staged: not part of this commit
        code, out = repo.run_cli("--staged")
        assert code == 1, out

    def test_a_staged_deletion_while_a_sibling_remains_passes(self, repo):
        repo.git("rm", "-q", CLOSING)
        assert repo.run_cli("--staged")[0] == 0

    def test_nothing_staged_passes(self, repo):
        code, out = repo.run_cli("--staged")
        assert code == 0, out
        assert "nothing to close-check" in out

    def test_a_repository_with_no_commits_yet_does_not_crash(self, tmp_path_factory):
        fresh = tmp_path_factory.mktemp("fresh")
        subprocess.run(["git", "-C", str(fresh), "init", "-q"], check=True)
        project(fresh, "p", status="building")
        subprocess.run(["git", "-C", str(fresh), "add", "-A"], check=True)
        code, out = GitRepo(fresh, cli).run_cli("--staged")
        assert code == 0, out
