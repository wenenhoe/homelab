"""Unit tests for generate_doc_indexes.py - table rendering and
section replacement. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import contextlib
import io

import pytest
from _doc_fixtures import project, revision
from doc_scripts import generate_doc_indexes as gen


class TestProjectsTable:
    @pytest.fixture
    def rows(self, root):
        return lambda: gen.render_standalone_projects_table(root).splitlines()[2:]

    def test_not_started_and_sort_order(self, root, rows):
        project(root, "a", status="not-started")
        project(root, "b", status="not-started")
        assert rows() == ["| [`a.md`](projects/a.md) | — | Not started | — | a summary |", "| [`b.md`](projects/b.md) | — | Not started | — | b summary |"]

    def test_lifecycle_statuses_and_the_blocked_flag(self, root, rows):
        project(root, "a", status="de-risking")
        project(root, "b", status="building", blocked=True, blocked_reason="needs new hardware")
        project(root, "c", status="done")
        assert rows() == [
            "| [`b.md`](projects/b.md) | — | Building | blocked: needs new hardware | b summary |",
            "| [`a.md`](projects/a.md) | — | De-risking | — | a summary |",
            "| [`c.md`](projects/c.md) | — | Done | — | c summary |",
        ]

    def test_a_project_whose_decision_rests_on_an_unsettled_one_says_so(self, root, rows):
        revision(root, "0001-a", 0, status="approved", relies_on=[{"adr": "ADR-0002", "reason": "Presupposes its boundary."}])
        revision(root, "0002-b", 0, status="working")
        project(root, "a", status="building", decision="ADR-0001/0")
        assert rows() == ["| [`a.md`](projects/a.md) | — | Building | rests on ADR-0002 (working) | a summary |"]

    def test_the_label_goes_once_the_target_is_settled(self, root, rows):
        revision(root, "0001-a", 0, status="approved", relies_on=[{"adr": "ADR-0002", "reason": "Presupposes its boundary."}])
        revision(root, "0002-b", 0, status="approved")
        project(root, "a", status="building", decision="ADR-0001/0")
        assert rows() == ["| [`a.md`](projects/a.md) | — | Building | — | a summary |"]

    def test_the_label_sits_beside_a_predecessor_and_in_the_initiative_view(self, root):
        revision(root, "0001-a", 0, status="approved", relies_on=[{"adr": "ADR-0002", "reason": "Presupposes its boundary."}])
        revision(root, "0002-b", 0, status="working")
        project(root, "base", status="building", super_project="init")
        project(root, "a", status="not-started", decision="ADR-0001/0", depends_on=[{"project": "PROJ-base", "reason": "needs it"}], super_project="init")
        assert "waiting on [`base.md`](projects/base.md); rests on ADR-0002 (working)" in gen.render_initiatives_table(root)

    def test_waiting_on_an_existing_predecessor(self, root, rows):
        project(root, "base", status="building")
        project(root, "next", depends_on=[{"project": "PROJ-base", "reason": "needs its output"}])
        assert rows()[1] == "| [`next.md`](projects/next.md) | — | Not started | waiting on [`base.md`](projects/base.md) | next summary |"

    def test_blocked_flag_and_dependency_combine(self, root, rows):
        project(root, "base")
        project(root, "next", status="building", blocked=True, blocked_reason="r", depends_on=[{"project": "PROJ-base", "reason": "x"}])
        assert "Building | blocked: r; waiting on [`base.md`](projects/base.md)" in rows()[0]


class TestNoBlocker:
    """An empty Blocker cell is derived, like "waiting on": never a stored status."""

    @pytest.fixture
    def rows(self, root):
        return lambda: gen.render_standalone_projects_table(root).splitlines()[2:]

    def test_not_started_with_an_approved_decision_is_ready(self, root, rows):
        revision(root, "0013-secret-storage", 0, status="approved")
        project(root, "a", decision="ADR-0013/0")
        assert rows() == ["| [`a.md`](projects/a.md) | — | Not started | — | a summary |"]

    def test_no_decision_means_nothing_gates_it(self, root, rows):
        project(root, "a")
        assert rows() == ["| [`a.md`](projects/a.md) | — | Not started | — | a summary |"]

    def test_a_working_decision_is_not_ready(self, root, rows):
        revision(root, "0013-secret-storage", 0, status="working")
        project(root, "a", decision="ADR-0013/0")
        assert rows() == [
            "| [`a.md`](projects/a.md) | — | Not started "
            "| waiting on [ADR-0013/0 (0013-secret-storage)](decisions/0013-secret-storage/revision-000.md) | a summary |"
        ]

    def test_a_decision_that_does_not_resolve_is_not_ready(self, root, rows):
        project(root, "a", decision="ADR-0099/0")
        assert rows() == ["| [`a.md`](projects/a.md) | — | Not started | waiting on ADR-0099/0 | a summary |"]

    def test_a_lettered_candidate_is_resolved_by_its_label(self, root, rows):
        revision(root, "0013-secret-storage", 0, letter="a", status="abandoned")
        revision(root, "0013-secret-storage", 0, letter="b", status="approved")
        project(root, "a", decision="ADR-0013/0-b")
        assert rows() == ["| [`a.md`](projects/a.md) | — | Not started | — | a summary |"]

    def test_an_existing_predecessor_means_waiting_not_ready(self, root, rows):
        project(root, "base", status="building")
        project(root, "next", depends_on=[{"project": "PROJ-base", "reason": "needs its output"}])
        assert rows()[1] == "| [`next.md`](projects/next.md) | — | Not started | waiting on [`base.md`](projects/base.md) | next summary |"

    def test_a_blocked_project_is_not_ready(self, root, rows):
        project(root, "a", blocked=True, blocked_reason="needs new hardware")
        assert rows() == ["| [`a.md`](projects/a.md) | — | Not started | blocked: needs new hardware | a summary |"]

    def test_only_not_started_projects_are_ever_ready(self, root, rows):
        revision(root, "0013-secret-storage", 0, status="approved")
        project(root, "a", status="building", decision="ADR-0013/0")
        project(root, "b", status="de-risking")
        assert rows() == ["| [`a.md`](projects/a.md) | — | Building | — | a summary |", "| [`b.md`](projects/b.md) | — | De-risking | — | b summary |"]

    def test_the_label_follows_the_decision_state_with_no_edit_to_the_project(self, root, rows):
        path = revision(root, "0013-secret-storage", 0, status="approved")
        project(root, "a", decision="ADR-0013/0")
        assert "| Not started | — |" in rows()[0]
        path.write_text(path.read_text(encoding="utf-8").replace("status: approved", "status: working"), encoding="utf-8")
        assert "| Not started | — |" not in rows()[0]
        assert "| Not started | waiting on [ADR-0013/0 (" in rows()[0]

    def test_every_view_that_renders_a_status_shows_it(self, root):
        revision(root, "0013-secret-storage", 0, status="approved")
        project(root, "a", decision="ADR-0013/0", super_project="s")
        project(root, "b", decision="ADR-0013/0")
        with contextlib.redirect_stderr(io.StringIO()):
            initiatives = gen.render_initiatives_table(root)
        assert initiatives.splitlines()[2].endswith("| Not started | — | a summary |")
        assert gen.render_standalone_projects_table(root).splitlines()[2] == "| [`b.md`](projects/b.md) | — | Not started | — | b summary |"


class TestWaitingOnADecisionLabel:
    """A not-started project whose decision is not approved says which revision it waits on."""

    @pytest.mark.parametrize(
        ("render", "fields", "link"),
        [
            pytest.param(gen.render_standalone_projects_table, {}, "decisions/0013-secret-storage/revision-000.md", id="projects-view"),
            pytest.param(gen.render_initiatives_table, {"super_project": "s"}, "decisions/0013-secret-storage/revision-000.md", id="super-projects-view"),
        ],
    )
    def test_the_link_is_relative_to_the_file_the_view_renders_into(self, root, render, fields, link):
        revision(root, "0013-secret-storage", 0, status="working")
        project(root, "a", decision="ADR-0013/0", **fields)
        project(root, "b", **fields)
        assert f"| Not started | waiting on [ADR-0013/0 (0013-secret-storage)]({link}) |" in render(root)

    def test_a_lettered_candidate_is_linked_by_its_label(self, root):
        revision(root, "0013-secret-storage", 0, letter="a", status="abandoned")
        revision(root, "0013-secret-storage", 0, letter="b", status="working")
        project(root, "a", decision="ADR-0013/0-b")
        assert (
            "| Not started | waiting on [ADR-0013/0-b (0013-secret-storage)](decisions/0013-secret-storage/revision-000-b.md) |"
            in gen.render_standalone_projects_table(root)
        )

    @pytest.mark.parametrize(
        ("fields", "expected"),
        [
            pytest.param({"status": "de-risking", "decision": "ADR-0013/0"}, ("De-risking", "—"), id="started"),
            pytest.param(
                {"blocked": True, "blocked_reason": "needs new hardware", "decision": "ADR-0013/0"},
                ("Not started", "blocked: needs new hardware"),
                id="blocked",
            ),
            pytest.param(
                {"depends_on": [{"project": "PROJ-base", "reason": "needs its output"}], "decision": "ADR-0013/0"},
                ("Not started", "waiting on [`base.md`](projects/base.md)"),
                id="waiting-on-a-project",
            ),
            pytest.param({}, ("Not started", "—"), id="no-decision"),
        ],
    )
    def test_only_the_case_nothing_else_explains_is_labelled(self, root, fields, expected):
        revision(root, "0013-secret-storage", 0, status="working")
        project(root, "base", status="building")
        project(root, "left-out", **fields)
        cells = gen.render_standalone_projects_table(root).splitlines()[-1].split("|")
        assert (cells[3].strip(), cells[4].strip()) == expected


class TestOrderByStatus:
    """The project tables list started work first, then spikes, then the rest, each by file name."""

    def names(self, render, root):
        return [row.split("|")[1].split("`")[1] for row in render(root).splitlines()[2:]]

    def test_building_then_de_risking_then_not_started_then_done(self, root):
        project(root, "a-idle")
        project(root, "b-done", status="done")
        project(root, "c-spike", status="de-risking")
        project(root, "d-build", status="building")
        project(root, "e-build", status="building")
        project(root, "f-idle")
        assert self.names(gen.render_standalone_projects_table, root) == ["d-build.md", "e-build.md", "c-spike.md", "a-idle.md", "f-idle.md", "b-done.md"]

    def test_the_super_projects_view_keeps_its_build_order(self, root):
        project(root, "a-first", super_project="s")
        project(root, "b-second", super_project="s", status="building", depends_on=[{"project": "PROJ-a-first", "reason": "x"}])
        project(root, "c-other", super_project="s")
        with contextlib.redirect_stderr(io.StringIO()):
            table = gen.render_initiatives_table(root)
        assert [line.split("|")[2].split("`")[1] for line in table.splitlines()[2:]] == ["a-first.md", "c-other.md", "b-second.md"]


class TestDecisionShortName:
    """`short` is required on every revision, so a resolved decision always has one."""

    def test_a_revision_with_a_short_name_is_linked_by_it(self, root):
        revision(root, "0013-secret-storage", 0, status="working", short="Secret storage")
        project(root, "a", decision="ADR-0013/0")
        assert "waiting on [ADR-0013/0 (Secret storage)](decisions/0013-secret-storage/revision-000.md)" in gen.render_standalone_projects_table(root)


class TestInitiativesTable:
    @pytest.fixture
    def order(self, root):
        def _order() -> list[str]:
            with contextlib.redirect_stderr(io.StringIO()):
                table = gen.render_initiatives_table(root)
            return [line.split("|")[2].strip().split("`")[1] for line in table.splitlines()[2:]]

        return _order

    def test_groups_by_label_and_skips_unlabelled(self, root):
        project(root, "a", super_project="pull-based-cd", status="building")
        project(root, "b", super_project="pull-based-cd")
        project(root, "c")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            table = gen.render_initiatives_table(root)
        assert table.splitlines()[2:] == [
            # Second row's initiative cell is blank: it's the same
            # initiative as the row above, and rows in one initiative
            # always sort contiguously.
            "| `pull-based-cd` | [`a.md`](projects/a.md) | — | Building | — | a summary |",
            # Blank cell renders as one space between its pipes, not
            # two — MD060's compact table style flags "|  |".
            "| | [`b.md`](projects/b.md) | — | Not started | — | b summary |",
        ]
        assert err.getvalue() == ""

    def test_the_table_has_no_track_or_phase_column(self, root):
        project(root, "a", super_project="cd")
        project(root, "b", super_project="cd")
        assert gen.render_initiatives_table(root).splitlines()[0] == "| Initiative | Project | Unblocks | Status | Blocker | Covers |"

    def test_initiative_cell_is_only_blanked_within_a_contiguous_run(self, root):
        project(root, "a1", super_project="a")
        project(root, "b1", super_project="b")
        project(root, "a2", super_project="a", depends_on=[{"project": "PROJ-a1", "reason": "x"}])
        table = gen.render_initiatives_table(root)
        # Sort groups by initiative first, so the two `a` rows land
        # together even though `a2` was declared before `b1`'s row here.
        assert [line.split("|")[1].strip() for line in table.splitlines()[2:]] == ["`a`", "", "`b`"]

    def test_dependency_depth_orders_projects_within_an_initiative(self, root, order):
        project(root, "a-last", super_project="t", depends_on=[{"project": "PROJ-z-first", "reason": "x"}])
        project(root, "z-first", super_project="t")
        assert order() == ["z-first.md", "a-last.md"]

    def test_independent_projects_fall_back_to_name(self, root, order):
        project(root, "b", super_project="t")
        project(root, "a", super_project="t")
        assert order() == ["a.md", "b.md"]

    def test_a_chain_reads_in_build_order(self, root, order):
        project(root, "core", super_project="t")
        project(root, "rehearse", super_project="t", depends_on=[{"project": "PROJ-core", "reason": "x"}])
        project(root, "day2", super_project="t", depends_on=[{"project": "PROJ-rehearse", "reason": "x"}])
        assert order() == ["core.md", "rehearse.md", "day2.md"]

    def test_initiatives_stay_grouped(self, root, order):
        project(root, "y1", super_project="y")
        project(root, "x2", super_project="x", depends_on=[{"project": "PROJ-x1", "reason": "x"}])
        project(root, "x1", super_project="x")
        project(root, "y2", super_project="y", depends_on=[{"project": "PROJ-y1", "reason": "x"}])
        assert order() == ["x1.md", "x2.md", "y1.md", "y2.md"]

    def test_a_dependency_cycle_does_not_hang_the_generator(self, root, order):
        project(root, "a", super_project="t", depends_on=[{"project": "PROJ-b", "reason": "x"}])
        project(root, "b", super_project="t", depends_on=[{"project": "PROJ-a", "reason": "x"}])
        assert sorted(order()) == ["a.md", "b.md"]

    def test_a_dependency_on_a_missing_project_is_ignored(self, root, order):
        project(root, "a", super_project="t", depends_on=[{"project": "PROJ-ghost", "reason": "x"}])
        project(root, "b", super_project="t")
        assert order() == ["a.md", "b.md"]

    def test_single_use_label_warns_but_still_renders(self, root):
        project(root, "a", super_project="typo-label")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            table = gen.render_initiatives_table(root)
        assert "typo-label" in err.getvalue()
        assert "`typo-label`" in table

    def test_no_labels(self, root):
        project(root, "a")
        assert gen.render_initiatives_table(root) == "No project is grouped into an initiative."


def initiatives(root, *names: str) -> None:
    """The initiative list a roadmap reads: a numbered list under `## Initiatives`, followed by another section."""
    items = "\n".join(f"{i}. `{name}` — what {name} delivers." for i, name in enumerate(names, 1))
    readme = root / "docs/projects/README.md"
    readme.parent.mkdir(parents=True, exist_ok=True)
    readme.write_text(
        f"# Projects\n\n## Initiatives\n\nIn this order.\n\n{items}\n\n## Lifecycle\n\n1. `not-an-initiative` — after the list.\n", encoding="utf-8"
    )


class TestRoadmapTable:
    @pytest.fixture
    def rows(self, root):
        return lambda: gen.render_roadmap_table(root).splitlines()[2:]

    def test_a_row_per_initiative_in_the_kept_order_then_the_projects_with_none(self, root, rows):
        initiatives(root, "zeta", "alpha")
        project(root, "a", super_project="alpha")
        project(root, "z", super_project="zeta")
        project(root, "loose")
        assert gen.render_roadmap_table(root).splitlines()[0] == "| Initiative | In progress | Startable | Waiting |"
        assert rows() == [
            "| `zeta` | — | [`z.md`](projects/z.md) | — |",
            "| `alpha` | — | [`a.md`](projects/a.md) | — |",
            "| (no initiative) | — | [`loose.md`](projects/loose.md) | — |",
        ]

    def test_the_last_row_is_there_when_every_project_has_an_initiative(self, root, rows):
        initiatives(root, "alpha")
        project(root, "a", super_project="alpha")
        assert rows()[-1] == "| (no initiative) | — | — | — |"

    def test_the_status_and_blocker_decide_the_column(self, root, rows):
        initiatives(root, "t")
        project(root, "build", super_project="t", status="building")
        project(root, "spike", super_project="t", status="de-risking")
        project(root, "ready", super_project="t")
        project(root, "stuck", super_project="t", blocked=True, blocked_reason="needs hardware")
        project(root, "after", super_project="t", depends_on=[{"project": "PROJ-ready", "reason": "x"}])
        project(root, "finished", super_project="t", status="done")
        assert rows()[0] == (
            "| `t` | [`build.md`](projects/build.md), [`spike.md`](projects/spike.md) | [`ready.md`](projects/ready.md) (unblocks 1) | "
            "[`stuck.md`](projects/stuck.md), [`after.md`](projects/after.md) |"
        )

    def test_a_project_waiting_on_an_unapproved_decision_is_waiting(self, root, rows):
        initiatives(root, "t")
        revision(root, "0001-a", 0, status="working")
        revision(root, "0002-b", 0, status="approved")
        project(root, "open", super_project="t", decision="ADR-0002/0")
        project(root, "undecided", super_project="t", decision="ADR-0001/0")
        assert rows()[0] == "| `t` | — | [`open.md`](projects/open.md) | [`undecided.md`](projects/undecided.md) |"

    def test_a_project_resting_on_an_unsettled_decision_is_waiting(self, root, rows):
        initiatives(root, "t")
        revision(root, "0001-a", 0, status="approved", relies_on=[{"adr": "ADR-0002", "reason": "Presupposes its boundary."}])
        revision(root, "0002-b", 0, status="working")
        project(root, "a", super_project="t", decision="ADR-0001/0")
        assert rows()[0] == "| `t` | — | — | [`a.md`](projects/a.md) |"

    def test_a_cell_lists_projects_by_dependency_depth_then_name(self, root, rows):
        initiatives(root, "t")
        project(root, "b", super_project="t", status="building")
        project(root, "a-late", super_project="t", status="building", depends_on=[{"project": "PROJ-z-first", "reason": "x"}])
        project(root, "z-first", super_project="t", status="building")
        assert rows()[0].split("|")[2].strip() == "[`b.md`](projects/b.md), [`z-first.md`](projects/z-first.md) (unblocks 1), [`a-late.md`](projects/a-late.md)"

    def test_a_project_with_no_initiative_goes_in_the_last_row_by_the_same_rules(self, root, rows):
        initiatives(root, "t")
        project(root, "a", super_project="t")
        project(root, "loose-build", status="building")
        project(root, "loose-wait", blocked=True, blocked_reason="needs hardware")
        assert rows()[-1] == "| (no initiative) | [`loose-build.md`](projects/loose-build.md) | — | [`loose-wait.md`](projects/loose-wait.md) |"

    def test_only_the_initiatives_section_is_read(self, root):
        initiatives(root, "t")
        project(root, "a", super_project="t")
        assert "not-an-initiative" not in gen.render_roadmap_table(root)

    def test_a_super_project_missing_from_the_list_fails(self, root):
        initiatives(root, "t")
        project(root, "a", super_project="t")
        project(root, "b", super_project="unplaced")
        with pytest.raises(SystemExit) as exc:
            gen.render_roadmap_table(root)
        assert str(exc.value) == "super_project 'unplaced' is not in the initiative list in docs/projects/README.md"

    def test_an_initiative_listed_twice_fails(self, root):
        initiatives(root, "t", "u", "t")
        project(root, "a", super_project="t")
        project(root, "b", super_project="u")
        with pytest.raises(SystemExit) as exc:
            gen.render_roadmap_table(root)
        assert str(exc.value) == "initiative 't' is listed more than once in docs/projects/README.md"

    def test_an_initiative_with_no_project_fails(self, root):
        initiatives(root, "t", "finished")
        project(root, "a", super_project="t")
        with pytest.raises(SystemExit) as exc:
            gen.render_roadmap_table(root)
        assert str(exc.value) == "initiative 'finished' in docs/projects/README.md has no project"

    def test_a_done_project_still_counts_as_a_project_of_its_initiative(self, root, rows):
        initiatives(root, "t")
        project(root, "a", super_project="t", status="done")
        assert rows()[0] == "| `t` | — | — | — |"

    def test_every_failure_is_named_at_once(self, root):
        initiatives(root, "t", "t", "gone")
        project(root, "a", super_project="t")
        project(root, "b", super_project="unplaced")
        with pytest.raises(SystemExit) as exc:
            gen.render_roadmap_table(root)
        assert str(exc.value).splitlines() == [
            "initiative 't' is listed more than once in docs/projects/README.md",
            "super_project 'unplaced' is not in the initiative list in docs/projects/README.md",
            "initiative 'gone' in docs/projects/README.md has no project",
        ]

    def test_a_readme_without_the_section_fails(self, root):
        project(root, "a")
        (root / "docs/projects/README.md").write_text("# Projects\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="no '## Initiatives' section"):
            gen.render_roadmap_table(root)

    def test_a_missing_readme_fails_the_same_way(self, root):
        project(root, "a")
        with pytest.raises(SystemExit, match="no '## Initiatives' section"):
            gen.render_roadmap_table(root)


class TestStandaloneProjectsTable:
    @pytest.fixture
    def rows(self, root):
        return lambda: gen.render_standalone_projects_table(root).splitlines()[2:]

    def test_only_projects_without_a_super_project_are_listed(self, root, rows):
        project(root, "a", super_project="pull-based-cd")
        project(root, "b")
        assert rows() == ["| [`b.md`](projects/b.md) | — | Not started | — | b summary |"]

    def test_links_and_waiting_on_use_the_projects_prefix(self, root, rows):
        project(root, "base")
        project(root, "next", depends_on=[{"project": "PROJ-base", "reason": "needs its output"}])
        assert rows() == [
            "| [`base.md`](projects/base.md) | 1 | Not started | — | base summary |",
            "| [`next.md`](projects/next.md) | — | Not started | waiting on [`base.md`](projects/base.md) | next summary |",
        ]

    def test_no_standalone_projects(self, root):
        project(root, "a", super_project="pull-based-cd")
        assert gen.render_standalone_projects_table(root) == "Every project belongs to a super-project."


class TestUnblocksCount:
    """Unblocks counts the existing projects that wait on a project, directly or through a chain."""

    @pytest.fixture
    def counts(self, root):
        def _counts() -> dict[str, str]:
            cells = (row.split("|") for row in gen.render_standalone_projects_table(root).splitlines()[2:])
            return {c[1].split("`")[1]: c[2].strip() for c in cells}

        return _counts

    @pytest.mark.parametrize(
        ("waits_on", "expected"),
        [
            pytest.param({"a": [], "b": []}, {"a.md": "—", "b.md": "—"}, id="unrelated"),
            pytest.param({"base": [], "x": ["base"], "y": ["base"]}, {"base.md": "2", "x.md": "—", "y.md": "—"}, id="direct"),
            pytest.param({"a": [], "b": ["a"], "c": ["b"]}, {"a.md": "2", "b.md": "1", "c.md": "—"}, id="chain"),
            pytest.param(
                {"top": [], "left": ["top"], "right": ["top"], "bottom": ["left", "right"]},
                {"top.md": "3", "left.md": "1", "right.md": "1", "bottom.md": "—"},
                id="two-paths-to-one-project-count-it-once",
            ),
            pytest.param({"a": ["b"], "b": ["a"]}, {"a.md": "1", "b.md": "1"}, id="cycle"),
            pytest.param({"a": ["a"]}, {"a.md": "—"}, id="self-dependency"),
            pytest.param({"a": ["ghost"]}, {"a.md": "—"}, id="missing-predecessor"),
        ],
    )
    def test_counts_dependents(self, root, counts, waits_on, expected):
        for name, predecessors in waits_on.items():
            project(root, name, depends_on=[{"project": f"PROJ-{p}", "reason": "needs its output"} for p in predecessors])
        assert counts() == expected

    def test_a_deleted_dependent_stops_counting_with_no_edit_to_the_project(self, root, counts):
        project(root, "base")
        dependent = project(root, "next", depends_on=[{"project": "PROJ-base", "reason": "needs its output"}])
        assert counts()["base.md"] == "1"
        dependent.unlink()
        assert counts()["base.md"] == "—"

    def test_every_project_view_carries_the_count(self, root):
        project(root, "base", status="building", super_project="s")
        project(root, "next", super_project="s", depends_on=[{"project": "PROJ-base", "reason": "needs its output"}])
        project(root, "lone-base", status="building")
        project(root, "lone-next", depends_on=[{"project": "PROJ-lone-base", "reason": "needs its output"}])
        assert "| [`base.md`](projects/base.md) | 1 | Building | — |" in gen.render_initiatives_table(root)
        assert "| [`lone-base.md`](projects/lone-base.md) | 1 | Building | — | lone-base summary |" in gen.render_standalone_projects_table(root)


class TestDecisionsAwaitingAProject:
    @pytest.fixture
    def adrs(self, root):
        return lambda: [row.split("|")[1].strip()[1:5] for row in gen.render_needs_project_table(root).splitlines()[2:]]

    def test_approved_revisions_come_before_working_ones_each_group_in_lineage_order(self, root, adrs):
        revision(root, "0002-b", 0, status="working")
        revision(root, "0003-c", 0, status="approved")
        revision(root, "0004-d", 0, status="working")
        revision(root, "0005-e", 0, status="approved")
        assert adrs() == ["0003", "0005", "0002", "0004"]

    def test_a_revision_a_project_names_is_left_out(self, root, adrs):
        revision(root, "0002-b", 0, status="working")
        revision(root, "0003-c", 0, status="approved")
        project(root, "p", status="building", decision="ADR-0003/0")
        assert adrs() == ["0002"]

    def test_a_pending_successor_sorts_by_its_own_status_not_its_accepted_parents(self, root, adrs):
        revision(root, "0001-a", 0, status="accepted")
        revision(root, "0001-a", 1, status="working", supersedes=0)
        revision(root, "0002-b", 0, status="approved")
        assert adrs() == ["0002", "0001"]


class TestLineagesIndex:
    def test_empty(self, root):
        assert gen.render_lineages_index(root) == "No decision lineages yet."

    def test_groups_by_topic_in_vocabulary_order(self, root):
        revision(
            root,
            "0004-docker-api-access",
            0,
            title="Container access to the Docker API",
            topic="deployment-platform",
            status="accepted",
            solution="Socket proxy",
        )
        revision(root, "0017-store-recovery", 0, title="Recovering the store", topic="secrets-store", status="accepted", solution="Split secrets")
        revision(root, "0001-host-config", 0, title="Host configuration", topic="deployment-platform", status="accepted", solution="Ansible")
        out = gen.render_lineages_index(root)
        assert out.index("### Deployment & platform") < out.index("### Secrets store")
        assert "### Backup" not in out
        assert out.index("0001-host-config") < out.index("0004-docker-api-access")
        assert (
            "| [0004](decisions/0004-docker-api-access/revision-000.md) "
            "| **Container access to the Docker API** — Where secrets live. | Socket proxy | Accepted | — |" in out
        )

    def test_multi_revision_lineage_shows_current_and_pending(self, root):
        revision(root, "0013-secret-storage", 0, status="superseded", superseded_by=1, solution="File cache")
        revision(root, "0013-secret-storage", 1, status="accepted", supersedes=0, solution="OpenBao", former_ids=["ADR-0027"])
        revision(root, "0013-secret-storage", 2, status="working", solution="Something newer")
        out = gen.render_lineages_index(root)
        assert "[0013](decisions/0013-secret-storage/revision-001.md)" in out
        assert "| OpenBao | Accepted (revision 1) | Revision 2 working; Formerly ADR-0027 |" in out

    def test_a_light_revision_is_marked_and_a_full_one_is_not(self, root):
        revision(root, "0013-secret-storage", 0, status="accepted", solution="Light one", weight="light")
        revision(root, "0014-other", 0, status="accepted", solution="Full one", weight="full")
        revision(root, "0015-third", 0, status="accepted", solution="Default one")
        out = gen.render_lineages_index(root)
        assert "| Light one | Accepted, light |" in out
        assert "| Full one | Accepted |" in out
        assert "| Default one | Accepted |" in out

    def test_the_original_is_labelled_when_a_successor_exists(self, root):
        revision(root, "0013-secret-storage", 0, status="accepted", solution="File cache")
        revision(root, "0013-secret-storage", 1, status="working", supersedes=0, solution="OpenBao")
        out = gen.render_lineages_index(root)
        assert "| File cache | Accepted (original) | Revision 1 working |" in out
        assert "revision 0" not in out

    def test_competing_candidates_are_shown_as_undecided(self, root):
        revision(root, "0044-trigger", 0, letter="a", status="working", solution="Pull-based agent")
        revision(root, "0044-trigger", 0, letter="b", status="working", solution="Private Gitea")
        out = gen.render_lineages_index(root)
        assert "[0044](decisions/0044-trigger/revision-000-a.md)" in out
        assert "Undecided between: (000-a) Pull-based agent; or (000-b) Private Gitea" in out
        assert "Working (000-a), Working (000-b)" in out
        assert "| Private Gitea |" not in out  # the newest candidate must not be presented as the current solution

    def test_open_revisions_in_different_generations_are_also_undecided(self, root):
        revision(root, "0044-trigger", 0, status="working", solution="A")
        revision(root, "0044-trigger", 1, status="working", solution="B")
        assert "Undecided between: (000) A; or (001) B" in gen.render_lineages_index(root)

    def test_an_approved_revision_with_a_successor_in_flight_is_also_undecided(self, root):
        revision(root, "0044-trigger", 0, status="approved", solution="A")
        revision(root, "0044-trigger", 1, status="working", supersedes=0, solution="B")
        assert "Approved (000), Working (001)" in gen.render_lineages_index(root)

    def test_the_winning_candidate_is_labelled_and_pending_replacements_are_listed(self, root):
        revision(root, "0044-trigger", 0, letter="a", status="accepted", solution="A")
        revision(root, "0044-trigger", 0, letter="b", status="abandoned", solution="B")
        revision(root, "0044-trigger", 1, letter="a", status="working", supersedes="0-a", solution="C")
        revision(root, "0044-trigger", 1, letter="b", status="working", supersedes="0-a", solution="D")
        out = gen.render_lineages_index(root)
        assert "Undecided" not in out
        assert "| A | Accepted (original (a)) | Revision 1-a working; Revision 1-b working |" in out

    def test_an_accepted_revision_means_not_undecided(self, root):
        revision(root, "0044-trigger", 0, status="accepted", solution="A")
        revision(root, "0044-trigger", 1, status="working", supersedes=0, solution="B")
        out = gen.render_lineages_index(root)
        assert "Undecided" not in out
        assert "| A | Accepted (original) | Revision 1 working |" in out

    def test_abandoned_alternatives_do_not_make_it_undecided(self, root):
        revision(root, "0044-trigger", 0, status="abandoned", solution="A")
        revision(root, "0044-trigger", 1, status="working", solution="B")
        out = gen.render_lineages_index(root)
        assert "Undecided" not in out
        assert "| B | Working (revision 1) |" in out

    def test_narrowed_by_and_related_back_pointers(self, root):
        revision(root, "0015-expiry", 0, status="accepted", topic="cloud-credentials", title="Credential expiry")
        revision(root, "0016-oci", 0, status="accepted", topic="cloud-credentials", title="OCI credentials", narrows="ADR-0015", related=["ADR-0014"])
        revision(root, "0014-r2", 0, status="accepted", topic="cloud-credentials", title="R2 rotation credential")
        out = gen.render_lineages_index(root)
        rows = {line.split("|")[1].strip()[1:5]: line for line in out.splitlines() if line.startswith("| [")}
        assert "Narrowed by [0016](decisions/0016-oci/revision-000.md)" in rows["0015"]
        assert "Narrowed by" not in rows["0016"]
        assert "Related: [0014](decisions/0014-r2/revision-000.md)" in rows["0016"]
        assert "Related: [0016](decisions/0016-oci/revision-000.md)" in rows["0014"]

    def test_a_declared_reliance_is_noted_with_the_targets_state(self, root):
        revision(root, "0001-a", 0, status="approved", title="A", relies_on=[{"adr": "ADR-0002", "reason": "Presupposes its boundary."}])
        revision(root, "0002-b", 0, status="working", title="B")
        out = gen.render_lineages_index(root)
        rows = {line.split("|")[1].strip()[1:5]: line for line in out.splitlines() if line.startswith("| [")}
        assert "Relies on [0002](decisions/0002-b/revision-000.md) (working)" in rows["0001"]
        assert "Relies on" not in rows["0002"]
        assert "Relies on [0002](decisions/0002-b/revision-000.md) (working)" in gen.render_decisions_by_number(root).splitlines()[2]

    def test_the_note_follows_the_target_once_it_is_settled(self, root):
        revision(root, "0001-a", 0, status="approved", title="A", relies_on=[{"adr": "ADR-0002", "reason": "Presupposes its boundary."}])
        revision(root, "0002-b", 0, status="approved", title="B")
        assert "Relies on [0002](decisions/0002-b/revision-000.md) (approved)" in gen.render_lineages_index(root)

    def test_pipes_in_text_are_escaped(self, root):
        revision(root, "0001-x", 0, status="accepted", solution="a | b")
        assert r"a \| b" in gen.render_lineages_index(root)


class TestDecisionsByNumber:
    def test_empty(self, root):
        assert gen.render_decisions_by_number(root) == "No decision lineages yet."

    def test_one_short_row_per_lineage_in_number_order_whatever_the_topic(self, root):
        revision(root, "0017-store-recovery", 0, short="Store recovery", topic="secrets-store", status="accepted")
        revision(root, "0004-docker-api-access", 0, short="Docker API access", topic="deployment-platform", status="accepted")
        revision(root, "0011-alerts", 0, short="Alert routing", topic="monitoring-alerting", status="accepted")
        assert gen.render_decisions_by_number(root).splitlines()[2:] == [
            "| [0004](decisions/0004-docker-api-access/revision-000.md) | Docker API access | Accepted | Deployment & platform | — |",
            "| [0011](decisions/0011-alerts/revision-000.md) | Alert routing | Accepted | Monitoring & alerting | — |",
            "| [0017](decisions/0017-store-recovery/revision-000.md) | Store recovery | Accepted | Secrets store | — |",
        ]

    def test_the_link_goes_to_the_revision_that_answers_the_problem(self, root):
        revision(root, "0013-secret-storage", 0, status="superseded", superseded_by=1)
        revision(root, "0013-secret-storage", 1, status="accepted", supersedes=0)
        assert "| [0013](decisions/0013-secret-storage/revision-001.md) |" in gen.render_decisions_by_number(root)

    def test_a_merged_lineages_old_number_and_a_pending_revision_are_in_the_notes(self, root):
        revision(root, "0013-secret-storage", 0, status="accepted", former_ids=["ADR-0027", "ADR-0029"])
        revision(root, "0013-secret-storage", 1, status="working")
        row = gen.render_decisions_by_number(root).splitlines()[2]
        assert row.endswith("| Accepted (original) | Secrets store | Revision 1 working; Formerly ADR-0027, ADR-0029 |")

    def test_competing_candidates_are_undecided_with_no_note_repeating_it(self, root):
        revision(root, "0044-trigger", 0, letter="a", status="working")
        revision(root, "0044-trigger", 0, letter="b", status="working")
        row = gen.render_decisions_by_number(root).splitlines()[2]
        assert "| Working (000-a), Working (000-b) | Secrets store | — |" in row

    def test_a_link_prefix_follows_the_file_rendered_into(self, root):
        revision(root, "0001-a", 0, status="accepted")
        assert "[0001](../decisions/0001-a/revision-000.md)" in gen.render_decisions_by_number(root, prefix="../decisions/")


class TestOpenDecisions:
    def test_empty(self, root):
        revision(root, "0001-a", 0, status="accepted")
        assert gen.render_open_decisions(root) == "No decision is open."

    def test_approved_before_working_each_group_in_lineage_order_and_closed_ones_left_out(self, root):
        revision(root, "0002-b", 0, status="working")
        revision(root, "0003-c", 0, status="approved")
        revision(root, "0004-d", 0, status="accepted")
        revision(root, "0005-e", 0, status="approved")
        assert [row.split("|")[1].strip()[1:5] for row in gen.render_open_decisions(root).splitlines()[2:]] == ["0003", "0005", "0002"]

    def test_a_decision_a_project_names_is_listed_with_its_projects_and_one_nobody_names_with_a_dash(self, root):
        revision(root, "0002-b", 0, status="approved")
        revision(root, "0003-c", 0, status="working")
        project(root, "p", decision="ADR-0002/0")
        project(root, "q", decision="ADR-0009/0", also_implements=["ADR-0002/0"])
        rows = gen.render_open_decisions(root).splitlines()[2:]
        assert rows[0].endswith("| Approved | [`p.md`](projects/p.md), [`q.md`](projects/q.md) |")
        assert rows[1].endswith("| Working | — |")

    def test_a_pending_successor_is_listed_under_its_own_revision(self, root):
        revision(root, "0001-a", 0, status="accepted")
        revision(root, "0001-a", 1, status="working", supersedes=0)
        assert gen.render_open_decisions(root).splitlines()[2].startswith("| [0001](decisions/0001-a/revision-001.md) | revision 1 |")

    def test_a_lettered_candidate_is_matched_to_a_project_by_its_label(self, root):
        revision(root, "0044-trigger", 0, letter="a", status="abandoned")
        revision(root, "0044-trigger", 0, letter="b", status="approved")
        project(root, "p", decision="ADR-0044/0-b")
        assert gen.render_open_decisions(root).splitlines()[2].endswith("| original (b) | 0044-trigger | Approved | [`p.md`](projects/p.md) |")


class TestHistory:
    def test_empty(self, root):
        revision(root, "0001-a", 0, status="accepted")
        assert gen.render_history(root) == "No revision has been superseded or abandoned."

    def test_a_superseded_revision_links_the_one_that_replaced_it(self, root):
        revision(root, "0013-secret-storage", 0, status="superseded", superseded_by=1)
        revision(root, "0013-secret-storage", 1, status="accepted", supersedes=0)
        assert gen.render_history(root).splitlines()[2:] == [
            "| [0013](decisions/0013-secret-storage/revision-000.md) | original | 0013-secret-storage | Superseded "
            "| [revision 1](decisions/0013-secret-storage/revision-001.md) |"
        ]

    def test_an_abandoned_candidate_is_listed_and_the_current_revisions_are_not(self, root):
        revision(root, "0044-trigger", 0, letter="a", status="abandoned")
        revision(root, "0044-trigger", 0, letter="b", status="accepted")
        revision(root, "0045-other", 0, status="working")
        rows = gen.render_history(root).splitlines()[2:]
        assert len(rows) == 1
        assert rows[0].startswith("| [0044](decisions/0044-trigger/revision-000-a.md) | original (a) |")
        assert rows[0].endswith("| Abandoned | — |")


class TestValidateAdrs:
    def test_two_directories_with_one_number_fail_naming_both(self, root):
        revision(root, "0089-alpha", 0)
        revision(root, "0089-bravo", 0)
        with pytest.raises(SystemExit, match=r"docs/decisions/0089-bravo: ADR-0089 is also used by 0089-alpha"):
            gen.validate_adrs(root)

    def test_the_failure_points_at_the_renumber_helper(self, root):
        revision(root, "0089-alpha", 0)
        revision(root, "0089-bravo", 0)
        with pytest.raises(SystemExit, match=r"python3 -m doc_scripts\.renumber_adr_patches"):
            gen.validate_adrs(root)

    def test_every_extra_directory_is_named(self, root):
        for name in ("0089-alpha", "0089-bravo", "0089-charlie"):
            revision(root, name, 0)
        with pytest.raises(SystemExit) as raised:
            gen.validate_adrs(root)
        message = str(raised.value)
        assert "0089-bravo: ADR-0089 is also used by 0089-alpha" in message
        assert "0089-charlie: ADR-0089 is also used by 0089-bravo" in message

    def test_a_file_directly_under_decisions_still_fails(self, root):
        (root / "docs" / "decisions").mkdir(parents=True)
        (root / "docs" / "decisions" / "notes.md").write_text("no frontmatter\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            gen.validate_adrs(root)


class TestSectionReplacement:
    DOC = "# T\n\nintro\n\n## Index\n\nold\n\n## Other\n\nkeep\n"

    def test_replaces_only_the_named_section(self):
        assert gen.replace_section(self.DOC, "Index", "new") == "# T\n\nintro\n\n## Index\n\nnew\n\n## Other\n\nkeep\n"

    def test_h3_headings_inside_a_section_do_not_end_it(self):
        doc = "## Lineages\n\n### A\n\nold\n\n### B\n\nold\n\n## Next\n\nkeep\n"
        assert gen.replace_section(doc, "Lineages", "new") == "## Lineages\n\nnew\n\n## Next\n\nkeep\n"

    def test_missing_required_section_fails(self, root):
        path = root / "README.md"
        path.write_text("# T\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="couldn't find"):
            gen.regenerate(path, "Index", "x")

    def test_optional_section_is_skipped_when_absent(self, root):
        path = root / "README.md"
        path.write_text("# T\n\n## Other\n\nkeep\n", encoding="utf-8")
        assert not gen.regenerate(path, "Lineages", "x", optional=True)
        assert path.read_text(encoding="utf-8") == "# T\n\n## Other\n\nkeep\n"

    def test_optional_section_is_replaced_when_present(self, root):
        path = root / "README.md"
        path.write_text("# T\n\n## Lineages\n\nold\n", encoding="utf-8")
        assert gen.regenerate(path, "Lineages", "new", optional=True)
        assert path.read_text(encoding="utf-8") == "# T\n\n## Lineages\n\nnew\n"


class TestEnsureSection:
    def test_a_missing_section_is_added_ahead_of_the_one_named(self, root):
        path = root / "README.md"
        path.write_text("# T\n\nintro\n\n## Next\n\nkeep\n", encoding="utf-8")
        gen.ensure_section(path, "Index", before="Next")
        gen.regenerate(path, "Index", "new")
        assert path.read_text(encoding="utf-8") == "# T\n\nintro\n\n## Index\n\nnew\n\n## Next\n\nkeep\n"

    def test_a_present_section_is_left_alone(self, root):
        path = root / "README.md"
        path.write_text("# T\n\n## Index\n\nold\n\n## Next\n\nkeep\n", encoding="utf-8")
        gen.ensure_section(path, "Index", before="Next")
        assert path.read_text(encoding="utf-8") == "# T\n\n## Index\n\nold\n\n## Next\n\nkeep\n"

    def test_with_no_section_to_add_it_before_the_file_is_unchanged(self, root):
        path = root / "README.md"
        path.write_text("# T\n", encoding="utf-8")
        gen.ensure_section(path, "Index", before="Next")
        assert path.read_text(encoding="utf-8") == "# T\n"


class TestActiveProjectWarnings:
    def make(self, root, n, status):
        for i in range(n):
            project(root, f"{status}-{i}", status=status)

    def test_at_the_limit_is_quiet(self, root):
        self.make(root, gen.ACTIVE_PROJECT_LIMIT, "building")
        assert gen.active_project_warnings(root) == []

    def test_building_and_de_risking_both_count(self, root):
        self.make(root, gen.ACTIVE_PROJECT_LIMIT - 1, "building")
        self.make(root, 2, "de-risking")
        [warning] = gen.active_project_warnings(root)
        assert f"{gen.ACTIVE_PROJECT_LIMIT + 1} projects" in warning

    def test_not_started_and_done_projects_do_not_count(self, root):
        self.make(root, gen.ACTIVE_PROJECT_LIMIT + 5, "not-started")
        assert gen.active_project_warnings(root) == []
