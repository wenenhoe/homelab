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
        return lambda: gen.render_projects_table(root).splitlines()[2:]

    def test_not_started_and_sort_order(self, root, rows):
        project(root, "a", status="not-started")
        project(root, "b", status="not-started")
        assert rows() == ["| [`a.md`](a.md) | Not started | a summary |", "| [`b.md`](b.md) | Not started | b summary |"]

    def test_lifecycle_statuses_and_the_blocked_flag(self, root, rows):
        project(root, "a", status="de-risking")
        project(root, "b", status="building", blocked=True, blocked_reason="needs new hardware")
        project(root, "c", status="done")
        assert rows() == [
            "| [`a.md`](a.md) | De-risking | a summary |",
            "| [`b.md`](b.md) | Building — blocked: needs new hardware | b summary |",
            "| [`c.md`](c.md) | Done | c summary |",
        ]

    def test_waiting_on_an_existing_predecessor(self, root, rows):
        project(root, "base", status="building")
        project(root, "next", depends_on=[{"project": "PROJ-base", "reason": "needs its output"}])
        assert rows()[1] == "| [`next.md`](next.md) | Not started — waiting on [`base.md`](base.md) | next summary |"

    def test_blocked_flag_and_dependency_combine(self, root, rows):
        project(root, "base")
        project(root, "next", status="building", blocked=True, blocked_reason="r", depends_on=[{"project": "PROJ-base", "reason": "x"}])
        assert "Building — blocked: r — waiting on [`base.md`](base.md)" in rows()[1]


class TestInitiativesTable:
    @pytest.fixture
    def order(self, root):
        def _order() -> list[str]:
            with contextlib.redirect_stderr(io.StringIO()):
                table = gen.render_initiatives_table(root)
            return [line.split("|")[4].strip().split("`")[1] for line in table.splitlines()[2:]]

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
            "| `pull-based-cd` | — | — | [`a.md`](projects/a.md) | Building |",
            # Blank cell renders as one space between its pipes, not
            # two — MD060's compact table style flags "|  |".
            "| | — | — | [`b.md`](projects/b.md) | Not started |",
        ]
        assert err.getvalue() == ""

    def test_track_and_phase_columns_and_ordering(self, root):
        project(root, "late", super_project="cd", track="security", phase="hardening")
        project(root, "early", super_project="cd", track="security", phase="bootstrap")
        project(root, "infra", super_project="cd", track="agent")
        project(root, "loose", super_project="cd")
        table = gen.render_initiatives_table(root)
        assert [line.split("|")[4].strip() for line in table.splitlines()[2:]] == [
            "[`loose.md`](projects/loose.md)",
            "[`infra.md`](projects/infra.md)",
            "[`early.md`](projects/early.md)",
            "[`late.md`](projects/late.md)",
        ]
        # `early` isn't the first row of the `cd` initiative, so its
        # initiative cell is blank even though Track/Phase print every row.
        assert "| | `security` | `bootstrap` | [`early.md`](projects/early.md) |" in table

    def test_initiative_cell_is_only_blanked_within_a_contiguous_run(self, root):
        project(root, "a1", super_project="a")
        project(root, "b1", super_project="b")
        project(root, "a2", super_project="a", depends_on=[{"project": "PROJ-a1", "reason": "x"}])
        table = gen.render_initiatives_table(root)
        # Sort groups by initiative first, so the two `a` rows land
        # together even though `a2` was declared before `b1`'s row here.
        assert [line.split("|")[1].strip() for line in table.splitlines()[2:]] == ["`a`", "", "`b`"]

    def test_tracks_read_in_build_order_not_alphabetical(self, root, order):
        project(root, "core", super_project="t", track="provisioning")
        project(root, "rehearse", super_project="t", track="migration", depends_on=[{"project": "PROJ-core", "reason": "x"}])
        project(root, "day2", super_project="t", track="opnsense", depends_on=[{"project": "PROJ-rehearse", "reason": "x"}])
        assert order() == ["core.md", "rehearse.md", "day2.md"]

    def test_numbered_phases_order_a_track_even_when_names_sort_the_other_way(self, root, order):
        project(root, "cutover", super_project="t", track="migration", phase="2-cutover")
        project(root, "rehearsal", super_project="t", track="migration", phase="1-rehearsal")
        assert order() == ["rehearsal.md", "cutover.md"]

    def test_an_explicit_phase_order_beats_inferred_depth(self, root, order):
        project(root, "outside", super_project="t", track="y")
        project(root, "first", super_project="t", track="x", phase="1-first", depends_on=[{"project": "PROJ-outside", "reason": "x"}])
        project(root, "second", super_project="t", track="x", phase="2-second")
        # `first` is deeper than `second`, but its phase says it reads first
        assert order() == ["first.md", "second.md", "outside.md"]

    def test_within_a_track_dependency_depth_orders_projects(self, root, order):
        project(root, "a-last", super_project="t", track="x", depends_on=[{"project": "PROJ-z-first", "reason": "x"}])
        project(root, "z-first", super_project="t", track="x")
        assert order() == ["z-first.md", "a-last.md"]

    def test_independent_tracks_fall_back_to_name(self, root, order):
        project(root, "b", super_project="t", track="beta")
        project(root, "a", super_project="t", track="alpha")
        assert order() == ["a.md", "b.md"]

    def test_a_tracks_rows_stay_together_when_the_chain_weaves_between_tracks(self, root, order):
        project(root, "early", super_project="t", track="alpha")
        project(root, "mid", super_project="t", track="beta", depends_on=[{"project": "PROJ-early", "reason": "x"}])
        project(root, "late", super_project="t", track="alpha", depends_on=[{"project": "PROJ-mid", "reason": "x"}])
        # by depth alone this would interleave alpha, beta, alpha
        assert order() == ["early.md", "late.md", "mid.md"]

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


class TestStandaloneProjectsTable:
    @pytest.fixture
    def rows(self, root):
        return lambda: gen.render_standalone_projects_table(root).splitlines()[2:]

    def test_only_projects_without_a_super_project_are_listed(self, root, rows):
        project(root, "a", super_project="pull-based-cd")
        project(root, "b")
        assert rows() == ["| [`b.md`](projects/b.md) | Not started | b summary |"]

    def test_links_and_waiting_on_use_the_projects_prefix(self, root, rows):
        project(root, "base")
        project(root, "next", depends_on=[{"project": "PROJ-base", "reason": "needs its output"}])
        assert rows() == [
            "| [`base.md`](projects/base.md) | Not started | base summary |",
            "| [`next.md`](projects/next.md) | Not started — waiting on [`base.md`](projects/base.md) | next summary |",
        ]

    def test_no_standalone_projects(self, root):
        project(root, "a", super_project="pull-based-cd")
        assert gen.render_standalone_projects_table(root) == "Every project belongs to a super-project."


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
            "| [0004](0004-docker-api-access/revision-000.md) | **Container access to the Docker API** — Where secrets live. | Socket proxy | Accepted | — |"
            in out
        )

    def test_multi_revision_lineage_shows_current_and_pending(self, root):
        revision(root, "0013-secret-storage", 0, status="superseded", superseded_by=1, solution="File cache")
        revision(root, "0013-secret-storage", 1, status="accepted", supersedes=0, solution="OpenBao", former_ids=["ADR-0027"])
        revision(root, "0013-secret-storage", 2, status="working", solution="Something newer")
        out = gen.render_lineages_index(root)
        assert "[0013](0013-secret-storage/revision-001.md)" in out
        assert "| OpenBao | Accepted (revision 1) | Revision 2 working; Formerly ADR-0027 |" in out

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
        assert "[0044](0044-trigger/revision-000-a.md)" in out
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
        assert "Narrowed by [0016](0016-oci/revision-000.md)" in rows["0015"]
        assert "Narrowed by" not in rows["0016"]
        assert "Related: [0014](0014-r2/revision-000.md)" in rows["0016"]
        assert "Related: [0016](0016-oci/revision-000.md)" in rows["0014"]

    def test_pipes_in_text_are_escaped(self, root):
        revision(root, "0001-x", 0, status="accepted", solution="a | b")
        assert r"a \| b" in gen.render_lineages_index(root)


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
