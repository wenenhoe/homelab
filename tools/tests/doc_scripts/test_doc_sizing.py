"""Tests for doc_sizing.py: the size warnings of ADR 0037 revision 5. Each rule has a case that
warns and a case that does not, so a rule that stops firing, or fires on everything, fails here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _doc_fixtures import project
from doc_scripts import doc_sizing as sizing
from doc_scripts.doc_scope import stages

ROW = "| {n} | {stage} | Not started | {exit} |\n"


def table(*rows: str, exit: str = "it works") -> str:
    head = "\n## Execution plan\n\n| # | Stage | Status | Exit condition |\n| :-: | :--- | :--- | :--- |\n"
    return head + "".join(ROW.format(n=n, stage=stage, exit=exit) for n, stage in enumerate(rows, 1))


def make(name: str, *rows: str, deps: tuple[str, ...] = (), decision: str | None = None, exit: str = "it works") -> sizing.Project:
    fm = {"id": f"PROJ-{name}", "title": name, "type": "project", "status": "building"}
    if deps:
        fm["depends_on"] = [{"project": f"PROJ-{d}", "reason": "needs it"} for d in deps]
    if decision:
        fm["decision"] = decision
    text = table(*rows, exit=exit)
    return sizing.Project(f"docs/projects/{name}.md", fm, stages(text), text)


class TestOneRow:
    def test_a_lone_one_row_project_warns(self):
        found = sizing.size_warnings([make("a", "Build"), make("b", "One", "Two")])
        assert len(found) == 1
        assert "a.md" in found[0]
        assert "one stage" in found[0]

    def test_a_one_row_project_another_project_depends_on_alone_does_not(self):
        assert sizing.size_warnings([make("a", "Build"), make("b", "One", "Two", deps=("a",))]) == []

    def test_a_project_that_depends_on_it_among_others_does_not_excuse_it(self):
        found = sizing.size_warnings([make("a", "Build"), make("c", "One", "Two"), make("b", "One", "Two", deps=("a", "c"))])
        assert any("a.md" in w for w in found)


class TestManyStages:
    def test_six_stages_do_not_warn(self):
        assert sizing.size_warnings([make("a", *"123456")]) == []

    def test_seven_stages_warn(self):
        found = sizing.size_warnings([make("a", *"1234567")])
        assert len(found) == 1
        assert "7 stages" in found[0]


class TestChained:
    def test_projects_chained_on_one_revision_warn(self):
        found = sizing.size_warnings([make("a", "1", "2", decision="ADR-0001/0"), make("b", "1", "2", decision="ADR-0001/0", deps=("a",))])
        assert len(found) == 1
        assert "chained" in found[0]
        assert "b.md" in found[0]

    def test_a_chain_across_two_revisions_does_not(self):
        assert sizing.size_warnings([make("a", "1", "2", decision="ADR-0001/0"), make("b", "1", "2", decision="ADR-0002/0", deps=("a",))]) == []

    def test_another_project_depending_on_the_first_alone_is_an_outside_reason(self):
        projects = [
            make("a", "1", "2", decision="ADR-0001/0"),
            make("b", "1", "2", decision="ADR-0001/0", deps=("a",)),
            make("c", "1", "2", deps=("a",)),
        ]
        assert sizing.size_warnings(projects) == []


class TestWaitingInProse:
    @pytest.mark.parametrize(
        "exit",
        [
            "waits on PROJ-other",
            "blocked until [other](other.md) closes",
            "after docs/projects/other.md lands",
            "once PROJ-other is done",
        ],
    )
    def test_a_stage_that_waits_on_another_project_warns(self, exit):
        found = sizing.size_warnings([make("a", "1", "2", exit=exit)])
        assert len(found) == 2
        assert all("waits on another project in prose" in w for w in found)

    @pytest.mark.parametrize("exit", ["it works", "waits on a timer", "after the role is applied the service restarts"])
    def test_a_stage_that_names_no_project_does_not(self, exit):
        assert sizing.size_warnings([make("a", "1", "2", exit=exit)]) == []


class TestAddedStage:
    BEFORE = "---\nstatus: building\n---\n" + table("One", "Two")

    def test_a_stage_added_to_a_building_project_warns(self):
        found = sizing.added_stage_warnings("docs/projects/a.md", self.BEFORE, "---\nstatus: building\n---\n" + table("One", "Two", "Three"))
        assert len(found) == 1
        assert "'Three'" in found[0]

    def test_a_reworded_stage_status_does_not(self):
        assert sizing.added_stage_warnings("docs/projects/a.md", self.BEFORE, self.BEFORE.replace("Not started", "In progress")) == []

    def test_a_project_that_was_not_building_does_not(self):
        before = self.BEFORE.replace("building", "not-started")
        assert sizing.added_stage_warnings("docs/projects/a.md", before, before + ROW.format(n=3, stage="Three", exit="x")) == []

    def test_a_new_doc_does_not(self):
        assert sizing.added_stage_warnings("docs/projects/a.md", None, self.BEFORE) == []


def test_load_projects_reads_every_project_doc_but_the_readme(root: Path):
    project(root, "a", status="not-started")
    (root / "docs/projects/README.md").write_text("# Projects\n", encoding="utf-8")
    assert [p.id for p in sizing.load_projects(root)] == ["PROJ-a"]
