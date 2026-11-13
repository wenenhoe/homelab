"""Tests for check_project_start.py and doc_start.py against a real temporary git
repository: which docs a change adds is exactly what mocks would get wrong.
Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _doc_fixtures import GitRepo, project, revision
from doc_scripts import check_project_start as cli

LINEAGE = "0001-x"


@pytest.fixture
def repo(root: Path) -> GitRepo:
    """main holds a working decision, an approved one, and a placeholder that already waits on the working one."""
    repo = GitRepo(root, cli)
    repo.git("init", "-q")
    repo.git("checkout", "-q", "-b", "main")
    revision(root, LINEAGE, 0, status="working")
    revision(root, "0002-y", 0, status="approved")
    project(root, "placeholder", status="not-started", decision="ADR-0001/0")
    repo.commit("base")
    return repo


class TestPullRequestMode:
    def test_a_new_not_started_project_on_a_working_decision_fails(self, repo):
        repo.branch()
        project(repo.root, "fresh", status="not-started", decision="ADR-0001/0")
        repo.commit("add")
        code, out = repo.pr()
        assert code == 1, out
        assert "docs/projects/fresh.md" in out
        assert "ADR-0001/0 is working" in out
        assert "plan: draft" in out

    @pytest.mark.parametrize(
        ("name", "fields"),
        [
            pytest.param("approved", {"status": "not-started", "decision": "ADR-0002/0"}, id="on an approved decision"),
            pytest.param("draft", {"status": "not-started", "decision": "ADR-0001/0", "plan": "draft"}, id="a draft plan on a working decision"),
            pytest.param("waiting", {"status": "de-risking", "decision": "ADR-0001/0", "plan": "draft"}, id="de-risking draft on a working decision"),
            pytest.param("free", {"status": "not-started"}, id="no decision"),
        ],
    )
    def test_the_allowed_starts_pass(self, repo, name, fields):
        repo.branch()
        project(repo.root, name, **fields)
        repo.commit("add")
        code, out = repo.pr()
        assert code == 0, out

    def test_a_placeholder_already_on_main_is_not_rejudged(self, repo):
        repo.branch()
        path = repo.root / "docs/projects/placeholder.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nmore prose\n", encoding="utf-8")
        repo.commit("edit")
        code, out = repo.pr()
        assert code == 0, out
        assert "nothing to start-check" in out

    def test_a_renamed_placeholder_is_judged_as_added(self, repo):
        repo.branch()
        repo.git("mv", "docs/projects/placeholder.md", "docs/projects/renamed.md")
        repo.commit("rename")
        code, out = repo.pr()
        assert code == 1, out

    def test_the_decision_becoming_approved_in_the_same_change_passes(self, repo):
        repo.branch()
        path = repo.root / f"docs/decisions/{LINEAGE}/revision-000.md"
        path.write_text(path.read_text(encoding="utf-8").replace("status: working", "status: approved"), encoding="utf-8")
        project(repo.root, "fresh", status="not-started", decision="ADR-0001/0")
        repo.commit("approve and add")
        code, out = repo.pr()
        assert code == 0, out

    def test_a_result_whose_docs_do_not_parse_fails_closed(self, repo):
        repo.branch()
        (repo.root / "docs/projects/fresh.md").write_text("no frontmatter here\n", encoding="utf-8")
        repo.commit("add a doc that does not parse")
        code, out = repo.pr()
        assert code == 1, out
        assert "missing frontmatter" in out
        assert str(repo.root) not in out


class TestStagedMode:
    def test_a_staged_new_project_on_a_working_decision_fails(self, repo):
        project(repo.root, "fresh", status="not-started", decision="ADR-0001/0")
        repo.git("add", "-A")
        code, out = repo.run_cli("--staged")
        assert code == 1, out

    def test_nothing_staged_passes(self, repo):
        code, out = repo.run_cli("--staged")
        assert code == 0, out
