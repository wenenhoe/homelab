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


PLAN = "\n## Execution plan\n\n| # | Stage | Status | Exit condition |\n| :-: | :--- | :--- | :--- |\n| 1 | {stage} | Not started | {exit} |\n"


def write_plan(repo: GitRepo, name: str, stage: str = "Build it", note: str = "it works", **fields) -> None:
    fields.setdefault("decision", "ADR-0002/0")
    project(repo.root, name, **fields).write_text(
        (repo.root / f"docs/projects/{name}.md").read_text(encoding="utf-8") + PLAN.format(stage=stage, exit=note), encoding="utf-8"
    )


class TestBuildingGate:
    """A project starts building with a confirmed plan and a scope (ADR 0037 revision 5)."""

    @pytest.fixture
    def waiting(self, repo) -> GitRepo:
        """Two approved-decision projects on main: one a draft plan with a scope, one a confirmed plan without."""
        write_plan(repo, "draft", plan="draft", allowed_paths=["docs/**"])
        write_plan(repo, "confirmed", allowed_paths=None)
        repo.commit("projects")
        repo.branch()
        return repo

    def start(self, repo, name, message="start", **fields) -> tuple[int, str]:
        stage = "Build it, again" if fields.pop("restage", False) else "Build it"
        write_plan(repo, name, stage=stage, status="building", **fields)
        repo.commit(message)
        return repo.pr()

    def test_a_confirmed_plan_with_a_scope_starts(self, waiting):
        code, out = self.start(waiting, "confirmed", allowed_paths=["docs/**"])
        assert code == 0, out

    def test_a_draft_that_is_still_a_draft_fails(self, waiting):
        code, out = self.start(waiting, "draft", plan="draft", allowed_paths=["docs/**"], restage=True)
        assert code == 1, out
        assert "plan: draft" in out

    def test_no_scope_fails(self, waiting):
        code, out = self.start(waiting, "confirmed")
        assert code == 1, out
        assert "no allowed_paths" in out

    def test_an_empty_scope_fails(self, waiting):
        code, out = self.start(waiting, "confirmed", allowed_paths=[])
        assert code == 1, out
        assert "allowed_paths" in out

    def test_a_draft_confirmed_with_a_changed_stage_table_starts(self, waiting):
        code, out = self.start(waiting, "draft", plan="confirmed", allowed_paths=["docs/**"], restage=True)
        assert code == 0, out

    def test_a_draft_confirmed_with_an_unchanged_stage_table_fails(self, waiting):
        code, out = self.start(waiting, "draft", plan="confirmed", allowed_paths=["docs/**"])
        assert code == 1, out
        assert "Plan-Confirmed: docs/projects/draft.md" in out

    def test_the_trailer_on_a_commit_of_the_change_excuses_an_unchanged_table(self, waiting):
        code, out = self.start(waiting, "draft", message="start\n\nPlan-Confirmed: docs/projects/draft.md", plan="confirmed", allowed_paths=["docs/**"])
        assert code == 0, out

    def test_a_trailer_for_another_project_does_not_excuse_it(self, waiting):
        code, out = self.start(waiting, "draft", message="start\n\nPlan-Confirmed: docs/projects/other.md", plan="confirmed", allowed_paths=["docs/**"])
        assert code == 1, out

    def test_a_project_already_building_is_not_regated(self, waiting):
        write_plan(waiting, "confirmed", status="building", allowed_paths=["docs/**"])
        waiting.commit("start")
        waiting.git("checkout", "-q", "-B", "main")
        waiting.branch("later")
        write_plan(waiting, "confirmed", status="building", allowed_paths=["docs/**", "src/**"], sweep_terms=["zzz-nothing"])
        waiting.commit("widen the scope")
        code, out = waiting.run_cli("--base", "main", "--head", "later")
        assert code == 0, out

    def test_a_project_that_is_building_cannot_narrow_its_scope(self, waiting):
        write_plan(waiting, "confirmed", status="building", allowed_paths=["docs/**", "src/**"])
        waiting.commit("start")
        waiting.git("checkout", "-q", "-B", "main")
        waiting.branch("later")
        write_plan(waiting, "confirmed", status="building", allowed_paths=["docs/**"])
        waiting.commit("narrow the scope")
        code, out = waiting.run_cli("--base", "main", "--head", "later")
        assert code == 1, out
        assert "drops `src/**`" in out

    def test_starting_needs_a_scope_that_covers_what_the_plan_names(self, waiting):
        waiting.write("src/app/tasks.yaml", "x: 1\n")
        waiting.commit("a file the plan names")
        waiting.git("checkout", "-q", "-B", "main")
        waiting.branch("later")
        write_plan(waiting, "confirmed", status="building", allowed_paths=["docs/**"], note="`src/app/tasks.yaml`")
        waiting.commit("start")
        code, out = waiting.run_cli("--base", "main", "--head", "later")
        assert code == 1, out
        assert "allowed_paths lacks" in out

    def test_starting_needs_a_scope_that_covers_every_sweep_hit(self, waiting):
        waiting.write("legacy/a.md", "widget\n")
        waiting.commit("a mention")
        waiting.git("checkout", "-q", "-B", "main")
        waiting.branch("later")
        write_plan(waiting, "confirmed", status="building", allowed_paths=["docs/**"], sweep_terms=["widget"])
        waiting.commit("start")
        code, out = waiting.run_cli("--base", "main", "--head", "later")
        assert code == 1, out
        assert 'mentions "widget"' in out

    def test_a_new_doc_that_starts_as_building_needs_a_scope(self, waiting):
        code, out = self.start(waiting, "fresh")
        assert code == 1, out
        assert "no allowed_paths" in out

    def test_staged_does_not_judge_the_trailer(self, waiting):
        write_plan(waiting, "draft", plan="confirmed", status="building", allowed_paths=["docs/**"])
        waiting.git("add", "-A")
        code, out = waiting.run_cli("--staged")
        assert code == 0, out

    def test_staged_still_fails_a_draft_or_a_missing_scope(self, waiting):
        write_plan(waiting, "confirmed", status="building")
        waiting.git("add", "-A")
        code, out = waiting.run_cli("--staged")
        assert code == 1, out
        assert "no allowed_paths" in out
