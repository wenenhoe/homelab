"""Tests for check_project_scope.py against a real temporary git repository -
the merge-base, staged-file, and path-quoting behavior is exactly what mocks
would get wrong. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from _doc_fixtures import GitRepo
from doc_scripts import check_project_scope as cli

PROJECT = "docs/projects/p.md"


def project_doc(paths: list[str], decision: str | None = None) -> str:
    lines = ["---", "id: PROJ-p", "title: p", "type: project", "status: building", "summary: s", "allowed_paths:", *[f"  - '{p}'" for p in paths]]
    if decision:
        lines.append(f"decision: {decision}")
    return "\n".join([*lines, "---", "", "# p", ""])


@pytest.fixture
def repo(root: Path) -> GitRepo:
    repo = GitRepo(root, cli)
    repo.git("init", "-q")
    repo.git("checkout", "-q", "-b", "main")
    repo.write(PROJECT, project_doc(["src/**"]))
    repo.write("src/a.py", "a = 1\n")
    repo.write("other/b.py", "b = 1\n")
    repo.commit("base")
    return repo


class TestPullRequestMode:
    def test_a_change_inside_the_scope_passes(self, repo):
        repo.branch()
        repo.write("src/a.py", "a = 2\n")
        repo.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, stage 1 started"))
        repo.commit("work")
        code, out = repo.pr()
        assert code == 0, out

    def test_a_change_outside_the_scope_fails_and_names_the_file(self, repo):
        repo.branch()
        repo.write("other/b.py", "b = 2\n")
        repo.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, stage 1 started"))
        repo.commit("stray")
        code, out = repo.pr()
        assert code == 1
        assert "other/b.py" in out
        assert "src/a.py" not in out

    def test_a_change_that_touches_no_project_doc_is_not_checked(self, repo):
        repo.branch()
        repo.write("other/b.py", "b = 2\n")
        repo.commit("unrelated fix")
        code, out = repo.pr()
        assert code == 0, out
        assert "nothing to scope" in out

    def test_a_change_cannot_widen_its_own_scope(self, repo):
        repo.branch()
        repo.write(PROJECT, project_doc(["src/**", "other/**"]))
        repo.write("other/b.py", "b = 2\n")
        repo.commit("widen and use it in one change")
        code, out = repo.pr()
        assert code == 1, out
        assert "other/b.py" in out

    def test_widening_on_its_own_is_fine(self, repo):
        repo.branch()
        repo.write(PROJECT, project_doc(["src/**", "other/**"]))
        repo.commit("widen")
        code, out = repo.pr()
        assert code == 0, out

    def test_a_branch_that_is_behind_is_not_blamed_for_mains_newer_commits(self, repo):
        repo.branch()
        repo.write("src/a.py", "a = 2\n")
        repo.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, started"))
        repo.commit("work")
        repo.git("checkout", "-q", "main")
        repo.write("other/c.py", "c = 1\n")  # main moves on, outside the scope
        repo.commit("someone else's change to main")
        code, out = repo.pr()  # a two-dot diff of main against feature would report other/c.py
        assert code == 0, out

    def test_a_brand_new_project_doc_has_no_scope_yet(self, repo):
        repo.branch()
        repo.write("docs/projects/new.md", project_doc(["only/here/**"]))
        repo.write("anything/goes.py", "x = 1\n")
        repo.commit("new project and its first work")
        code, out = repo.pr()
        assert code == 0, out

    def test_renames_and_deletions_count_as_touching_both_paths(self, repo):
        repo.branch()
        repo.git("mv", "src/a.py", "other/a.py")  # leaves the scope
        repo.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, moved"))
        repo.commit("move out")
        code, out = repo.pr()
        assert code == 1
        assert "other/a.py" in out
        repo.git("checkout", "-q", "main")
        repo.git("branch", "-q", "-D", "feature")
        repo.branch()
        repo.git("rm", "-q", "other/b.py")
        repo.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, deleted"))
        repo.commit("delete outside")
        code, out = repo.pr()
        assert code == 1
        assert "other/b.py" in out

    def test_moving_a_file_into_the_scope_still_counts_as_touching_where_it_came_from(self, repo):
        repo.branch()
        repo.git("mv", "other/b.py", "src/b.py")  # rename detection would show only the in-scope destination
        repo.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, moved in"))
        repo.commit("move in")
        code, out = repo.pr()
        assert code == 1, out
        assert "other/b.py" in out

    def test_paths_with_spaces_and_unicode_are_reported_intact(self, repo):
        repo.branch()
        repo.write("other/we ird é.py", "x = 1\n")
        repo.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, odd"))
        repo.commit("odd name")
        code, out = repo.pr()
        assert code == 1
        assert "other/we ird é.py" in out

    def test_the_linked_decision_revision_may_change(self, repo):
        repo.write(PROJECT, project_doc(["src/**"], decision="ADR-0001/0"))
        repo.write("docs/decisions/0001-x/revision-000.md", "adr\n")
        repo.write("docs/decisions/0001-x/revision-001.md", "adr\n")
        repo.commit("link a decision")
        repo.branch()
        repo.write("docs/decisions/0001-x/revision-000.md", "adr, edited\n")
        repo.write(PROJECT, project_doc(["src/**"], decision="ADR-0001/0").replace("# p", "# p, x"))
        repo.commit("the permitted ADR edit")
        assert repo.pr()[0] == 0
        repo.write("docs/decisions/0001-x/revision-001.md", "adr, edited\n")
        repo.commit("a neighbour, not the linked one")
        assert repo.pr()[0] == 1


class TestStagedMode:
    def test_staged_changes_outside_the_scope_fail(self, repo):
        repo.write("other/b.py", "b = 2\n")
        repo.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, started"))
        repo.git("add", "-A")
        code, out = repo.run_cli("--staged")
        assert code == 1
        assert "other/b.py" in out

    def test_staged_changes_inside_the_scope_pass(self, repo):
        repo.write("src/a.py", "a = 2\n")
        repo.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, started"))
        repo.git("add", "-A")
        assert repo.run_cli("--staged")[0] == 0

    def test_unstaged_changes_are_ignored(self, repo):
        repo.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, started"))
        repo.git("add", "-A")
        repo.write("other/b.py", "b = 2\n")  # edited but not staged: not part of this commit
        assert repo.run_cli("--staged")[0] == 0

    def test_nothing_staged_passes(self, repo):
        code, out = repo.run_cli("--staged")
        assert code == 0, out

    def test_a_repository_with_no_commits_yet_does_not_crash(self, tmp_path_factory):
        fresh = tmp_path_factory.mktemp("fresh")
        subprocess.run(["git", "-C", str(fresh), "init", "-q"], check=True)
        (fresh / "docs/projects").mkdir(parents=True)
        (fresh / "docs/projects/p.md").write_text(project_doc(["src/**"]), encoding="utf-8")
        subprocess.run(["git", "-C", str(fresh), "add", "-A"], check=True)
        code, out = GitRepo(fresh, cli).run_cli("--staged")
        assert code == 0, out
