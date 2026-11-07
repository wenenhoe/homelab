"""Unit tests for doc_explorations.py and the exploration rules in
doc_frontmatter.py: the frontmatter shape, the one-way reference rule and the
planning view's dates. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from datetime import date

import pytest
from _doc_fixtures import GitRepo, assert_one_error, revision, write_doc
from doc_scripts import doc_explorations as explorations
from doc_scripts import generate_doc_indexes as generator


def exploration(root, slug="where-state-lives", **overrides):
    fm = {
        "id": f"EXP-{slug}",
        "title": "Where does the state live?",
        "type": "exploration",
        "status": "open",
        "summary": "Weighing two homes for state.",
        "topic": "deployment-platform",
    }
    fm.update(overrides)
    return write_doc(root, f"docs/explorations/{slug}.md", fm)


class TestFrontmatter:
    def test_a_well_formed_exploration_loads(self, root):
        exploration(root)
        [(path, fm)] = explorations.load_explorations(root)
        assert path.name == "where-state-lives.md"
        assert fm["status"] == "open"

    @pytest.mark.parametrize(
        ("overrides", "fragment"),
        [
            ({"id": "EXP-something-else"}, "expected EXP-where-state-lives"),
            ({"id": "where-state-lives"}, "must be EXP-"),
            ({"status": "closed"}, "isn't valid"),
            ({"type": "adr"}, "doesn't match its location"),
            ({"topic": "nonsense"}, "isn't one of"),
            ({"summary": ""}, "non-empty 'summary'"),
            ({"related": "ADR-0013"}, "list of ADR ids"),
        ],
    )
    def test_a_bad_field_is_refused(self, root, overrides, fragment):
        exploration(root, **overrides)
        with pytest.raises(SystemExit, match=fragment):
            explorations.load_explorations(root)

    def test_readme_and_template_are_not_explorations(self, root):
        write_doc(root, "docs/explorations/README.md", {"id": "x"})
        write_doc(root, "docs/explorations/TEMPLATE.md", {"id": "y"})
        assert explorations.load_explorations(root) == []

    def test_no_directory_is_no_explorations(self, root):
        assert explorations.load_explorations(root) == []
        assert explorations.exploration_errors(root) == []


class TestErrors:
    def test_related_must_be_a_real_lineage(self, root):
        revision(root, "0013-secret-storage", 0)
        exploration(root, related=["ADR-0013"])
        assert explorations.exploration_errors(root) == []
        exploration(root, slug="other", related=["ADR-0099"])
        assert_one_error(explorations.exploration_errors(root), "other.md", "ADR-0099")

    def test_a_decision_naming_an_exploration_fails(self, root):
        exploration(root)
        revision(root, "0013-secret-storage", 0, body="See docs/explorations/where-state-lives.md for the options.\n")
        assert_one_error(explorations.exploration_errors(root), "0013-secret-storage/revision-000.md", "where-state-lives.md")

    def test_a_topic_doc_a_comment_and_a_project_naming_one_fail(self, root):
        exploration(root)
        for rel in ("docs/topics/a.md", "ansible/roles/x/tasks/main.yaml", "tools/helper.py", "docs/projects/p.md"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("# see docs/explorations/where-state-lives.md\n", encoding="utf-8")
        assert len(explorations.exploration_errors(root)) == 4

    def test_the_planning_view_and_the_explorations_themselves_may_name_one(self, root):
        exploration(root)
        exploration(root, slug="second")
        (root / "docs/explorations/second.md").write_text(
            (root / "docs/explorations/second.md").read_text() + "\nAlso docs/explorations/where-state-lives.md.\n", encoding="utf-8"
        )
        (root / "docs/project-planning.md").write_text("| [x](explorations/where-state-lives.md) docs/explorations/where-state-lives.md |\n", encoding="utf-8")
        assert explorations.exploration_errors(root) == []

    def test_naming_the_readme_or_template_is_not_naming_an_exploration(self, root):
        (root / "docs").mkdir()
        (root / "docs/a.md").write_text("docs/explorations/README.md and docs/explorations/TEMPLATE.md\n", encoding="utf-8")
        assert explorations.exploration_errors(root) == []


class TestLastChanged:
    """An uncommitted change is dated today: the hooks that regenerate the planning view
    run before the commit that holds the file exists."""

    PATH = "docs/explorations/where-state-lives.md"
    OLD = date(2020, 1, 2)

    def repo(self, root, monkeypatch):
        repo = GitRepo(root, generator)
        repo.git("init", "-q", "-b", "main")
        exploration(root)
        monkeypatch.setenv("GIT_COMMITTER_DATE", "2020-01-02T12:00:00+0000")
        repo.commit("add")
        monkeypatch.delenv("GIT_COMMITTER_DATE")
        return repo

    def changed(self, root, today=date(2030, 6, 7)):
        return explorations.last_commit_date(root, root / self.PATH, today)

    def test_a_committed_file_has_its_commit_date(self, root, monkeypatch):
        self.repo(root, monkeypatch)
        assert self.changed(root) == self.OLD

    def test_an_untracked_file_is_dated_today(self, root):
        GitRepo(root, generator).git("init", "-q", "-b", "main")
        exploration(root)
        assert self.changed(root) == date(2030, 6, 7)

    def test_a_staged_new_file_is_dated_today(self, root):
        repo = GitRepo(root, generator)
        repo.git("init", "-q", "-b", "main")
        exploration(root)
        repo.git("add", "-A")
        assert self.changed(root) == date(2030, 6, 7)

    @pytest.mark.parametrize("staged", [False, True], ids=["unstaged", "staged"])
    def test_an_edit_not_committed_yet_is_dated_today(self, root, monkeypatch, staged):
        repo = self.repo(root, monkeypatch)
        exploration(root, summary="Reworded.")
        if staged:
            repo.git("add", "-A")
        assert self.changed(root) == date(2030, 6, 7)

    def test_a_file_whose_change_is_committed_is_dated_by_that_commit(self, root, monkeypatch):
        repo = self.repo(root, monkeypatch)
        exploration(root, summary="Reworded.")
        repo.commit("edit")
        assert self.changed(root) == date.today()

    def test_another_files_change_does_not_date_this_one(self, root, monkeypatch):
        self.repo(root, monkeypatch)
        exploration(root, slug="other")
        assert self.changed(root) == self.OLD

    def test_without_git_the_date_is_unknown(self, root):
        exploration(root)
        assert self.changed(root) is None

    def test_the_planning_view_dates_a_new_file_and_sorts_it_last(self, root, monkeypatch):
        repo = self.repo(root, monkeypatch)
        exploration(root, slug="b-new")
        lines = generator.render_explorations_table(root).splitlines()
        assert lines[2].endswith("| 2020-01-02 |")
        assert lines[3].endswith(f"| {date.today().isoformat()} |")
        assert repo.git("status", "--porcelain").strip() == "?? docs/explorations/b-new.md"


class TestPlanningView:
    def test_no_exploration_says_so(self, root):
        assert generator.render_explorations_table(root) == "No exploration is open."

    def test_the_table_lists_the_oldest_change_first(self, root):
        repo = GitRepo(root, generator)
        repo.git("init", "-q", "-b", "main")
        exploration(root, slug="a-first")
        repo.commit("first")
        exploration(root, slug="b-second", title="Second | question")
        repo.commit("second")
        lines = generator.render_explorations_table(root).splitlines()
        assert lines[0].startswith("| Exploration | Question | Last changed |")
        assert "[`a-first.md`](explorations/a-first.md)" in lines[2]
        assert r"Second \| question" in lines[3]
